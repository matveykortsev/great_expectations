from typing import Dict, List, Optional, Set, Union

import numpy as np

from great_expectations.rule_based_profiler.config import ParameterBuilderConfig
from great_expectations.rule_based_profiler.helpers.util import (
    get_parameter_value_and_validate_return_type,
)
from great_expectations.rule_based_profiler.parameter_builder import (
    MetricMultiBatchParameterBuilder,
)
from great_expectations.rule_based_profiler.types import (
    FULLY_QUALIFIED_PARAMETER_NAME_METADATA_KEY,
    FULLY_QUALIFIED_PARAMETER_NAME_VALUE_KEY,
    Domain,
    MetricValue,
    MetricValues,
    ParameterContainer,
    ParameterNode,
)
from great_expectations.types.attributes import Attributes


class MeanTableColumnsSetMatchMultiBatchParameterBuilder(
    MetricMultiBatchParameterBuilder
):
    """
    Compute mean match ratio (as a fraction) of "table.columns" metric across every Batch of data given.
    """

    exclude_field_names: Set[
        str
    ] = MetricMultiBatchParameterBuilder.exclude_field_names | {
        "metric_name",
        "enforce_numeric_metric",
        "replace_nan_with_zero",
        "reduce_scalar_metric",
    }

    def __init__(
        self,
        name: str,
        metric_domain_kwargs: Optional[Union[str, dict]] = None,
        metric_value_kwargs: Optional[Union[str, dict]] = None,
        evaluation_parameter_builder_configs: Optional[
            List[ParameterBuilderConfig]
        ] = None,
        json_serialize: Union[str, bool] = True,
        data_context: Optional["BaseDataContext"] = None,  # noqa: F821
    ) -> None:
        """
        Args:
            name: the name of this parameter -- this is user-specified parameter name (from configuration);
            it is not the fully-qualified parameter name; a fully-qualified parameter name must start with "$parameter."
            and may contain one or more subsequent parts (e.g., "$parameter.<my_param_from_config>.<metric_name>").
            metric_domain_kwargs: used in MetricConfiguration
            metric_value_kwargs: used in MetricConfiguration
            evaluation_parameter_builder_configs: ParameterBuilder configurations, executing and making whose respective
            ParameterBuilder objects' outputs available (as fully-qualified parameter names) is pre-requisite.
            These "ParameterBuilder" configurations help build parameters needed for this "ParameterBuilder".
            json_serialize: If True (default), convert computed value to JSON prior to saving results.
            data_context: BaseDataContext associated with this ParameterBuilder
        """
        super().__init__(
            name=name,
            metric_name="table.columns",
            metric_domain_kwargs=metric_domain_kwargs,
            metric_value_kwargs=metric_value_kwargs,
            enforce_numeric_metric=False,
            replace_nan_with_zero=False,
            reduce_scalar_metric=True,
            evaluation_parameter_builder_configs=evaluation_parameter_builder_configs,
            json_serialize=json_serialize,
            data_context=data_context,
        )

    def _build_parameters(
        self,
        domain: Domain,
        variables: Optional[ParameterContainer] = None,
        parameters: Optional[Dict[str, ParameterContainer]] = None,
        recompute_existing_parameter_values: bool = False,
    ) -> Attributes:
        """
        Builds ParameterContainer object that holds ParameterNode objects with attribute name-value pairs and details.

        Returns:
            Attributes object, containing computed parameter values and parameter computation details metadata.
        """
        # Compute "table.columns" metric value for each Batch object.
        super().build_parameters(
            domain=domain,
            variables=variables,
            parameters=parameters,
            parameter_computation_impl=super()._build_parameters,
            json_serialize=False,
            recompute_existing_parameter_values=recompute_existing_parameter_values,
        )

        # Retrieve "table.columns" metric values for all Batch objects.
        parameter_node: ParameterNode = get_parameter_value_and_validate_return_type(
            domain=domain,
            parameter_reference=self.fully_qualified_parameter_name,
            expected_return_type=None,
            variables=variables,
            parameters=parameters,
        )
        table_columns_names_multi_batch_value: MetricValues = parameter_node[
            FULLY_QUALIFIED_PARAMETER_NAME_VALUE_KEY
        ]

        one_batch_table_columns_names_value: MetricValue
        multi_batch_table_columns_names_sets_as_list: List[Set[str]] = [
            set(one_batch_table_columns_names_value.tolist())
            for one_batch_table_columns_names_value in table_columns_names_multi_batch_value
        ]

        multi_batch_table_columns_names_as_set: Set[str] = set().union(
            *multi_batch_table_columns_names_sets_as_list
        )

        one_batch_table_columns_names_set: Set[str]
        mean_table_columns_set_match: np.float64 = np.mean(
            np.array(
                [
                    1
                    if one_batch_table_columns_names_set
                    == multi_batch_table_columns_names_as_set
                    else 0
                    for one_batch_table_columns_names_set in multi_batch_table_columns_names_sets_as_list
                ]
            )
        )

        return Attributes(
            {
                FULLY_QUALIFIED_PARAMETER_NAME_VALUE_KEY: mean_table_columns_set_match,
                FULLY_QUALIFIED_PARAMETER_NAME_METADATA_KEY: parameter_node[
                    FULLY_QUALIFIED_PARAMETER_NAME_METADATA_KEY
                ],
            }
        )