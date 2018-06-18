# ensemble_model class

from __future__ import absolute_import

from cobra.core.object import Object
from cobra.core import Model
from cobra.core import DictList

import cobra
import random
import pandas as pd

class Ensemble(Object):
    """
    Ensemble of metabolic models

    Parameters
    ----------
    identifier : string
        The identifier to associate with the ensemble as a string.

    list_of_models : list of cobra.core.Model
        Either a list of existing Model objects in which case a new Model
        object is instantiated and an ensemble is constructed using the list of
        Models, or None/empty list, in which case an ensemble is created with
        empty attributes.

    name : string
        Human-readable name for the ensemble

    Attributes
    ----------
    base_model : Model
        A cobra.core.Model that contains all variable and invariable components
        of an ensemble.
    members : DictList
        A DictList where the key is the member identifier and the value is a
        Member
    features : DictList
        A DictList where the key is the feature identifier and the value is a
        Feature
    """
    def __init__(self,list_of_models=[], identifier=None, name=None):
        Object.init(self,identifier,name)
        if len(list_of_models) > 1:
            if not all(isinstance(x, Model) for x in list_of_models):
                raise AttributeError("list_of_models may only contain cobra.core.Model objects")
            self.features = DictList()
            self._populate_features_base(list_of_models)
            self._populate_base(list_of_models)
            self._populate_members(list_of_models)

        else:
            if len(list_of_models) == 0:
                self.base_model = Model(id_or_model=identifier+'_base_model',\
                                        name=name)
            else:
                if not isinstance(list_of_models[0], Model):
                    raise AttributeError("list_of_models may only contain cobra.core.Model objects")
                self.base_model = list_of_models[0]

    def _populate_features_base(self,list_of_models):
        all_reactions = set()
        base_model = list_of_models[0].copy()
        all_reactions = all_reactions + set([rxn.id for rxn in base_model.reactions])
        for model in list_of_models:
            new_reactions = set([rxn.id for rxn in model.reactions]) - \
                                all_reactions
            reactions_to_add = [model.reactions.get_by_id(rxn) for rxn in new_reactions]
            base_model.add_reactions(reactions_to_add)
            all_reactions = all_reactions + set([rxn.id for rxn in model.reactions])

        all_reactions = list(all_reactions)
        variable_reactions = []
        for reaction in all_reactions:
            rxn_vals = {}
            for model in list_of_models:
                rxn_vals[model.id] = {}
                rxn = model.reactions.get_by_id(reaction)
                for reaction_attribute in REACTION_ATTRIBUTES:
                    rxn_vals[model.id][reaction_attribute] = \
                        getattr(rxn,reaction_attribute)

            rxn_vals = pd.DataFrame(rxn_vals).T
            for reaction_attribute in REACTION_ATTRIBUTES:
                if len(rxn_vals[reaction_attribute].unique()) > 1:
                    feature = Feature(ensemble=self, base_component=reaction,\
                                        component_attribute=reaction_attribute,\
                                        states=rxn_vals.to_dict())
                    self.features += feature
                    variable_reactions.append(reaction)

        self.base_model = base_model





        # for model in list_of_models:
        #     for reaction in model.reactions:
        #         if not reaction.id in feature_dict.keys():
        #             feature_dict[reaction.id] = {}
        #
        #         for reaction_attribute in reaction_featuretypes:
        #             if not reaction_attribute in feature_dict[reaction.id].keys():
        #                 feature_dict[reaction.id][reaction_attribute] = {}
        #             attribute_value = getattr(reaction,reaction_feature)
        #             if attribute_value in feature_dict[reaction][reaction_attribute]:
        #             feature_dict[reaction][reaction_attribute] = \
        #                 getattr(reaction,reaction_feature)

    def __init__(self,base_id,model_list=None,join_method="concurrent",join_size=1):
        """
        Parameters
        ----------
        model_list: list of cobra.core.Model objects
            List of models to generate a single Ensemble object from.
        base_id: string
            identifier which will be assigned as the Ensemble's id.
        join_method: string
            Indicates the method used to construct the ensemble from model_list.
            Can be either "concurrent" or "iterative". Choose "concurrent" if
            the number of models is sufficiently small such that they can all be
            loaded into memory at the same time (not recommended for more than
            dozens of models with ~1000 reactions each). Otherwise, "iterative"
            will only load one model in memory at any given time; slower than
            "concurrent", but more memory efficient (required for large groups
            of large models).
        join_size: int
            Number of models to add to the ensemble during each iteration. Can
            only be used if join_method="iterative". Higher values consume more
            memory but should run more quickly. Default value is 1.
        """

        if join_method not in ["concurrent","iterative"]:
            raise ValueError("join_method must be either 'concurrent' or 'iterative'")

        self.features = pd.DataFrame()
        self.states = pd.DataFrame()
        self.id=base_id
        if not model_list:
            self.base_model = cobra.core.Model(base_id+'_base_model')
        else:
            if join_method == "concurrent":
                self.base_model = self._create_base_model(model_list,base_id=base_id+'_base_model')
                set_features_states(self,model_list=model_list)
            elif join_method == "iterative":
                self.base_model = cobra.core.Model(base_id+'_base_model')
                set_features_states(self,model_list[0:join_size])
                remainder = len(model_list) % join_size
                steps = int(len(model_list)/join_size)
                for i in range(steps):
                    model_group = model_list[(i+1)*join_size:i+2*join_size]
                    print(model_group)
                    print(self.features,self.states)
                    #self.add_models(model_group)
                    update_features_states(self,model_group)
                if remainder > 0:
                    update_features_states(self,model_list[-1*remainder:])
                    #self.add_models(model_list[-1*remainder:])


    def _apply_state(self,model_id):
        '''
        Set the base model to the state for the given model_name. Used as a helper
        function to more easily utilize utility functions from cobra (e.g.
        single reaction/gene deletions).

        '''
        model_states = self.states.loc[model_id]
        for reaction in model_states.index:
            if model_states.loc[reaction]:
                rxn.lower_bound = self.features.loc[reaction,'lower_bound']
                rxn.upper_bound = self.features.loc[reaction,'upper_bound']
            else:
                rxn.lower_bound = 0
                rxn.upper_bound = 0

    def _create_base_model(self,model_list,base_id='ensemble base'):
        '''
        Creates a base model from a list of universal models. Base models
        contain all reactions present in a list of models.
        '''
        base_model = cobra.Model(base_id)
        for model in model_list:
            rxns_to_add = []
            for reaction in model.reactions:
                if reaction.id not in [rxn.id for rxn in base_model.reactions]:
                    rxns_to_add.append(reaction.copy())
            base_model.add_reactions(rxns_to_add)
            base_model.repair()

        return base_model


def set_features_states(ensemble,model_list):
    """
    Sets the ensemble.features and ensemble.states dataframes given a list
    of input models. Used when creating a new ensemble. To update features
    and states of an existing ensemble when adding additional models, use
    _update_features_states.

    Parameters
    ----------
    model_list: list of cobra.core.Model objects
        List of models to generate a single Ensemble object from.
    """

    # if the model list is of length 1, there aren't any variable reactions.
    if len(model_list) == 1:
        ensemble.features = pd.DataFrame()
        ensemble.states = pd.DataFrame()
        ensemble.base_model = model_list[0]
    else:
        # Get list of every reaction present in all models
        reaction_set = set()
        for model in model_list:
            model_reactions = set([reaction.id for reaction in model.reactions])
            if len(reaction_set) > 0:
                reaction_set = reaction_set & model_reactions
            else:
                reaction_set = model_reactions
        reaction_list = list(reaction_set)
        for model in model_list:

            variable_reactions = {}
            reactions_different = [rxn for rxn in model.reactions if rxn.id not in reaction_list]
            for reaction in reactions_different:
                if not reaction.id in variable_reactions.keys():
                    variable_reactions[reaction.id] = {'lower_bound':model.reactions.get_by_id(reaction.id).lower_bound,\
                                                        'upper_bound':model.reactions.get_by_id(reaction.id).upper_bound,\
                                                        'type':'reaction',\
                                                        'model_identifier':reaction.id}
            #model_states = pd.DataFrame({feature:True for feature in variable_reactions.keys()},index=[model.id])
            features = pd.DataFrame(variable_reactions).T

            if len(ensemble.features) > 0:
                new_df = pd.concat([ensemble.features,features])
                # get rid of duplicate entries, ignoring feature_count since the
                # newly concatenated featured from this model won't have them yet
                duplicate_features = new_df.duplicated(new_df.columns.difference(['feature_count']))
                new_df['in_new_model'] = new_df.duplicated(new_df.columns.difference(['feature_count']),keep=False)

                new_df = new_df[~duplicate_features] # remove true duplicates

                # get the feature counts for remaining features with duplicate model identifiers
                new_df['feature_count'] = new_df.groupby('model_identifier').cumcount()

                # reassign the index based on new feature counts
                new_df.index = new_df['model_identifier'] + '_' + new_df['feature_count'].astype(str)
                new_df.loc[[rowlabel for rowlabel in new_df.index if rowlabel not in ensemble.features.index],['in_new_model']] = True

                # record the model states using the new feature IDs
                model_states = pd.DataFrame(new_df['in_new_model']).T
                model_states.index = [model.id]

                # drop the inventory column and reassign ensemble.features
                new_df = new_df.drop('in_new_model',axis=1)
                ensemble.features = new_df

                # reassign the states. Order matters here, so write stringent tests for this.
                new_df = pd.concat([ensemble.states,model_states])
                ensemble.states = new_df.fillna(False)
            else:
                ensemble.features = features#ensemble.features.join(features,how='outer')
                ensemble.features['feature_count'] = 0
                ensemble.features.index = ensemble.features['model_identifier']\
                                            + '_' + \
                                            ensemble.features['feature_count'].astype(str)
            #self.features = self.features.join(features,how='outer')
                model_states = pd.DataFrame({feature:True for feature in variable_reactions.keys()},index=[model.id])
                ensemble.states = ensemble.states.join(model_states,how='outer')
                ensemble.states.columns = ensemble.features.index

def update_features_states(old_ensemble,model_list):
    """
    Updates the ensemble.features and ensemble.states dataframes given a list
    of input models. Used when adding additional models to an ensemble. To
    set features and states for a new ensemble, use set_features_states.

    Parameters
    ----------
    model_list: list of cobra.core.Model objects
        List of models to add to this Ensemble object.
    """

    #if the existing ensemble only contains the base, just create from scratch
    if len(old_ensemble.features.index) < 1:
        print([old_ensemble.base_model]+model_list)
        new_ensemble = Ensemble(old_ensemble.id,[old_ensemble.base_model]+model_list)
        old_ensemble.base_model = new_ensemble.base_model
        old_ensemble.features = new_ensemble.features
        old_ensemble.states = new_ensemble.states
    else:

        new_ensemble = Ensemble(base_id='new_models',model_list=model_list)
        # Copy the attributes from the old ensemble, which we will update and reassign
        updated_features = old_ensemble.features.copy()
        updated_states = old_ensemble.states.copy()
        updated_base = old_ensemble.base_model.copy()

        # get the reactions that are in both bases, the old base, and the new base. This will need modification when features for elements other than reactions are implemented
        old_reactions = [rxn.id for rxn in old_ensemble.base_model]
        new_reactions = [rxn.id for rxn in new_ensemble.base_model]
        base_rxns_in_both = list(set(old_reactions) & set(new_reactions))
        base_rxns_in_old = list(set(old_reactions) - set(new_reactions))
        base_rxns_in_new = list(set(new_reactions) - set(old_reactions))
        # For reactions in both base models, we don't need to uypdate the base model
        for reaction in base_rxns_in_both:
            all_features_in_old = old_ensemble.features.loc[old_ensemble.features['model_identifer'] == reaction]
            if len(new_ensemble.features) > 0:
                all_features_in_new = old_ensemble.features.loc[new_ensemble.features['model_identifer'] == reaction]
                all_features_in_both = pd.concat([all_features_in_old,all_features_in_new])
                features_only_in_both = all_features.loc[all_features.duplicated(all_features.columns.difference(['feature_count']),keep=False)]
            else:
                all_features_in_new = pd.DataFrame()
                features_only_in_both = pd.DataFrame()

            features_in_both_and_old = pd.concat(all_features_in_old,features_only_in_both)
            features_only_in_old = all_features_in_old.loc[features_in_both_and_old.duplicated(keep=False)]

            features_in_both_and_new = pd.concat(all_features_in_new,features_only_in_both)
            features_only_in_new = all_features_in_new.loc[features_in_both_and_new.duplicated(keep=False)]

            _resolve_from_both_bases(features_only_in_old,new_ensemble,old_ensemble,updated_features,updated_states,features_in='old')
            _resolve_from_both_bases(features_only_in_new,new_ensemble,old_ensemble,updated_features,updated_states,features_in='new')
            _resolve_from_both_bases(features_only_in_both,new_ensemble,old_ensemble,updated_features,updated_states,features_in='both')
            # for feature_id in features_only_in_old.index.tolist():
            #     feature = features_only_in_old.loc[feature]
            #     if feature['type'] == 'reaction':
            #         check_params = {'lower_bound':new_ensemble.base_model.reactions.get_by_id(reaction).lower_bound,\
            #                         'upper_bound':new_ensemble.base_model.reactions.get_by_id(reaction).upper_bound}
            #     else:
            #         raise AssertionError('Unsupported feature type passed. Only reactions are currently supported')
            #     # check if the values for the reaction in the new base are equal to the feature params
            #     found = False
            #     for param in check_params.keys():
            #         compare_feature = [feature[param] == check_params[param] for param in check_params.keys()]
            #         if sum(compare_feature) == len(check_params.keys()):
            #                          updated_states[new_ensemble.states.index,feature.index] = True
            #                          found = True
            #                          break
            #
            #     if not found:
            #         new_feature = {'type':feature['type'],'model_identifier':feature['model_identifer']}
            #         new_feature.update({param:check_params[param] for param in check_params.keys()})
            #         # get the feature count for the model identifier in this feature
            #         existing_feature_count = updated_features.loc[updated_features['model_identifer'] == new_feature['model_identifier'],'feature_count'].max()
            #         new_feature['feature_count'] = existing_feature_count + 1
            #         new_feature = pd.DataFrame(new_feature,index=new_feature['model_identifier']+'_'+new_feature['feature_count'])
            #         # update the features and states with the new feature
            #         updated_features = pd.concat([updated_features,new_feature])
            #         updated_features = updated_features.fillna(False)
            #         updated_states[new_feature['model_identifier']] = True

def _resolve_from_both_bases(features_only_in,new_ensemble,old_ensemble,updated_features,updated_states,features_in='old'):
    if features_in=='old':
        for feature_id in features_only_in.index.tolist():
            feature = features_only_in.loc[feature_id]
            found = _find_feature_from_base(feature,new_ensemble)
            if found:
                updated_states[new_ensemble.states.index,feature_id] = True
                break
        if not found:
            feature = features_only_in.loc[features_only_in.index.tolist()[0]]
            new_feature = {'type':feature['type'],'model_identifier':feature['model_identifer']}
            if feature['type'] == 'reaction':
                check_params = {'lower_bound':new_ensemble.base_model.reactions.get_by_id(feature['model_identifier']).lower_bound,\
                                'upper_bound':new_ensemble.base_model.reactions.get_by_id(feature['model_identifier']).upper_bound}
            else:
                raise AssertionError('Unsupported feature type passed. Only reactions are currently supported')

            new_feature.update({param:check_params[param] for param in check_params.keys()})
            # get the feature count for the model identifier in this feature
            existing_feature_count = updated_features.loc[updated_features['model_identifer'] == new_feature['model_identifier'],'feature_count'].max()
            new_feature['feature_count'] = existing_feature_count + 1
            new_feature = pd.DataFrame(new_feature,index=new_feature['model_identifier']+'_'+new_feature['feature_count'])
            # update the features and states with the new feature
            updated_features = pd.concat([updated_features,new_feature])
            updated_features = updated_features.fillna(False)
            updated_states[new_ensemble.states.index,new_feature['model_identifier']] = True # might need to update updated_states to include models from the new ensemble prior to this

    elif features_in=='new':
        for feature_id in features_only_in.index.tolist():
            feature = features_only_in.loc[feature]
            found = _find_feature_from_base(feature,old_ensemble)
            if found:
                # if the feature is only in the new ensemble,
                updated_states[old_ensemble.states.index,feature_id] = True
                break
        if not found:
            feature = features_only_in.loc[features_only_in.index.tolist()[0]]
            new_feature = {'type':feature['type'],'model_identifier':feature['model_identifer']}
            if feature['type'] == 'reaction':
                check_params = {'lower_bound':old_ensemble.base_model.reactions.get_by_id(feature['model_identifier']).lower_bound,\
                                'upper_bound':old_ensemble.base_model.reactions.get_by_id(feature['model_identifier']).upper_bound}
            else:
                raise AssertionError('Unsupported feature type passed. Only reactions are currently supported')

            new_feature.update({param:check_params[param] for param in check_params.keys()})
            # get the feature count for the model identifier in this feature
            existing_feature_count = updated_features.loc[updated_features['model_identifer'] == new_feature['model_identifier'],'feature_count'].max()
            new_feature['feature_count'] = existing_feature_count + 1
            new_feature = pd.DataFrame(new_feature,index=new_feature['model_identifier']+'_'+new_feature['feature_count'])
            # update the features and states with the new feature
            updated_features = pd.concat([updated_features,new_feature])
            updated_features = updated_features.fillna(False)
            updated_states[old_ensemble.states.index,new_feature['model_identifier']] = True # might need to update updated_states to include models from the new ensemble prior to this

    elif features_in=='both':
        for feature_id in features_only_in.index.tolist():
            feature = features_only_in.loc[feature]
            # These features have the same values

def _find_feature_from_base(feature,ensemble):
    if feature['type'] == 'reaction':
        check_params = {'lower_bound':ensemble.base_model.reactions.get_by_id(feature['model_identifier']).lower_bound,\
                        'upper_bound':ensemble.base_model.reactions.get_by_id(feature['model_identifier']).upper_bound}
    else:
        raise AssertionError('Unsupported feature type passed. Only reactions are currently supported')
    # check if the values for the reaction in the new base are equal to the feature params
    found = False
    for param in check_params.keys():
        compare_feature = [feature[param] == check_params[param] for param in check_params.keys()]
        if sum(compare_feature) == len(check_params.keys()):
                         found = True
                         break


def update_base_with_union(base_rxns_in_both,old_ensemble,new_ensemble)
        # create a new ensemble from the input list
        # if len(model_list) == 1:
        #     # are any
        # else:
        #     new_ensemble = Ensemble(base_id='new_models',model_list=model_list)
        #     #current_ensemble._update_features(new_ensemble)
        #     #current_ensemble._update_states(new_ensemble)
        #     #current_ensemble._update_base(new_ensemble)
        #
        #     new_features = pd.concat([current_ensemble.features,new_ensemble.features])
        #     new_features = new_features.fillna(False)
        #     #if 'feature_count' in new_features.columns.tolist
        #     duplicate_features = new_features.duplicated(new_features.columns.difference(['feature_count']))
        #     new_features.loc[new_ensemble.features.index,'old_feature_count'] = new_ensemble.features['feature_count']
        #
        #     new_features = new_features[~duplicate_features] #remove true duplicates
        #
        #     new_features['feature_count'] = new_features.groupby('model_identifier').cumcount()
        #
        #     new_features.index = new_features['model_identifier'] + '_' + new_features['feature_count']
        #
        #     # reassign feature_ids in the state dataframe for new ensemble being added
        #     old_feature_count = new_features.loc[~new_features['old_feature_count'].isna(),'old_feature_count']
        #     new_feature_count = new_features.loc[~new_features['old_feature_count'].isna(),'feature_count']
        #     old_feature_ids = new_features.loc[~new_features['old_feature_count'].isna(),'model_identifier'] + '_' + old_feature_count
        #     new_feature_ids = new_features.loc[~new_features['old_feature_count'].isna(),'model_identifier'] + '_' + new_feature_count
        #     translate_feature_counts = dict(zip(old_feature_ids,new_feature_ids))
        #
        #     new_ensemble.states = new_ensemble.states.rename(columns=translate_feature_counts)
        #
        #
        #     # need to determine the state of features in each ensemble that are specified in only one of the two ensembles' features:
        #     # for features in the existing ensemble, we also need to check whether features not specified in the new ensemble are ON or OFF in the entire new ensemble.
        #     # for features in the new ensemble, we need to check whether features in the new ensemble not in the old features are ON or OFF in the entire old ensemble
        #
        #
        #     old_features_constant_in_new = [feature for feature in current_ensemble.features.index.tolist() if feature not in new_ensemble.features.index.tolist()]
        #     for feature in old_features_constant_in_new:
        #         # get the parameters for the feature in the new base model
        #         feature_params = current_ensemble.features.loc[feature]
        #         if feature_params['type'] == 'reaction': # put this check here for later implementation of additional feature types
        #             reaction = new_ensemble.base_model.reactions.get_by_id(feature_params['model_identifier'])
        #             check_params = {'lower_bound':reaction.lower_bound,\
        #                             'upper_bound':reaction.upper_bound}
        #         else:
        #             raise AssertionError('Unsupported feature type passed. Only reactions are currently supported')
        #
        #         # check whether the value in the new base model corresponds to an existing feature.
        #         # when the feature is found, stop searching.
        #         existing_features = new_features.loc[new_features['model_identifier'] == feature_params['model_identifer']]
        #         found = False
        #         for feature_index in existing_features.index.tolist():
        #             this_feature = existing_features.loc[feature_index]
        #
        #             compare_feature = [this_feature[param] == check_params[param] for param in check_params.keys()]
        #             if sum(compare_feature) == len(check_params.keys()):
        #                 new_ensemble.states[new_ensemble.states.index,this_feature.index] = True
        #                 found = True
        #                 break
        #
        #         # if the feature wasn't found, we create a new feature with the values from the new ensemble.
        #         if not found:
        #             new_feature = {'type':feature_params['type'],'model_identifier':feature_params['model_identifer']}
        #             new_feature.update({param:check_param[param] for param in check_params.keys()})
        #             # get the feature count for the model identifier in this feature
        #             existing_feature_count = new_features.loc[new_features['model_identifer'] == new_feature['model_identifier'],'feature_count'].max()
        #             new_feature['feature_count'] = existing_feature_count + 1
        #             new_feature = pd.DataFrame(new_feature,index=new_feature['model_identifier']+'_'+new_feature['feature_count'])
        #             # update the features and states with the new feature
        #             new_features = pd.concat([new_features,new_feature])
        #             new_features = new_features.fillna(False)
        #             new_ensemble.states[new_feature['model_identifier']] = True
        #
        #
        #     new_features_constant_in_old = [feature for feature in new_ensemble.features.index.tolist() if feature not in current_ensemble.features.index.tolist()]
        #     for feature in new_features_constant_in_old:
        #         feature_params = new_ensemble.features.loc[feature]
        #         if feature_params['type'] == 'reaction': # put this check here for later implementation of additional feature types
        #             reaction = current_ensemble.base_model.reactions.get_by_id(feature_params['model_identifier'])
        #             check_params = {'lower_bound':reaction.lower_bound,\
        #                             'upper_bound':reaction.upper_bound}
        #         else:
        #             raise AssertionError('Unsupported feature type passed. Only reactions are currently supported')
        #         # if a new feature is variable, but was constant in the old ensemble,
        #         # we need to get the possible values of the feature in the new ensemble,
        #         # and check whether the value in the base model for the old ensemble is the
        #         # same as one of the features in the new ensemble. If it is the same,
        #         # set the state for all old models to be True for that feature. If the values
        #         # are not identical to an existing feature, create a new feature and set the state
        #         # to True for all old models.
        #
        #         # check whether the value in the old base model corresponds to an existing feature in either ensemble.
        #         # when the feature is found, stop searching.
        #         existing_features = new_features.loc[new_features['model_identifier'] == feature_params['model_identifer']]
        #         found = False
        #         for feature_index in existing_features.index.tolist():
        #             this_feature = existing_features.loc[feature_index]
        #
        #             compare_feature = [this_feature[param] == check_params[param] for param in check_params.keys()]
        #             if sum(compare_feature) == len(check_params.keys()):
        #                 current_ensemble.states[current_ensemble.states.index,this_feature.index] = True
        #                 found = True
        #                 break
        #
        #         # if the feature wasn't found, we create a new feature with the values from the old ensemble.
        #         if not found:
        #             new_feature = {'type':feature_params['type'],'model_identifier':feature_params['model_identifer']}
        #             new_feature.update({param:check_param[param] for param in check_params.keys()})
        #             # get the feature count for the model identifier in this feature
        #             existing_feature_count = new_features.loc[new_features['model_identifer'] == new_feature['model_identifier'],'feature_count'].max()
        #             new_feature['feature_count'] = existing_feature_count + 1
        #             new_feature = pd.DataFrame(new_feature,index=new_feature['model_identifier']+'_'+new_feature['feature_count'])
        #             # update the features and states with the new feature
        #             new_features = pd.concat([new_features,new_feature])
        #             new_features = new_features.fillna(False)
        #             current_ensemble.states[new_feature['model_identifier']] = True
        #
        #
        #     # tasks:
        #     # 1. update base with new reactions
        #     # 2. add reactions to features that are now newly variable and update model states for new feature
        #     # 3.
        #     # determine reactions that need to be added to the diff (present in new ensemble and not in base)
        #
        #
        #
        #     # merge the old ensemble with the new ensemble
        #     all_features = pd.concat([current_ensemble.features,new_ensemble.features])
        #     current_ensemble.features = all_features[~all_features.index.duplicated(keep='first')]
        #     all_states = pd.concat([current_ensemble.states,new_ensemble.states])
        #     current_ensemble.states = all_states.fillna(False)


def add_models(current_ensemble,model_list):
    '''
    Adds an additional model to an existing ensemble. Modifies base_model to
    include any unique reactions and updates the reaction diff.

    When creating an ensemble for more than hundreds of models, creating an
    empty base model, then adding the models individually using add_models
    can prevent the need to load all models simultaneously (e.g. you can
    load and add one at a time, then clear the individual model from memory).
    This methods conserves memory relative to Ensemble_model.init, but may take
    slightly longer to run as the reaction diff is recalculated for each
    addition and more calls to base_model.add_reactions() are made.

    WARNING: currently requires starting from an ensemble object which
    contains at least one base model. If an empty ensemble is used with
    add_models(), the diff is considered to be every reaction. We should
    refactor to enable starting with an empty model, since this makes
    code a little cleaner for the user.
    '''
