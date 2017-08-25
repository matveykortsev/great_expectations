import pandas as pd
import numpy as np
from scipy import stats
import re
from dateutil.parser import parse
from datetime import datetime
import json
from functools import wraps
import inspect

from .base import DataSet
from .util import is_valid_partition_object, remove_empty_intervals


class MetaPandasDataSet(DataSet):

    def __init__(self, *args, **kwargs):
        super(MetaPandasDataSet, self).__init__(*args, **kwargs)

    @classmethod
    def column_map_expectation(cls, func):
        """
        The column_map_expectation decorator handles boilerplate issues surrounding the common pattern of evaluating
        truthiness of some condition on a per row basis.

        NOTE: The MetaPandasDataSet implementation replaces the "column" parameter supplied by the user with a pandas Series
        object containing the actual column from the relevant pandas dataframe. This simplifies the implementing expectation
        logic while preserving the standard DataSet signature and expected behavior.

        Further, the column_map_expectation provides a unique set of output_format options and handles the optional "mostly" parameter.
        """

        @cls.expectation(inspect.getargspec(func)[0][1:])
        @wraps(func)
        def inner_wrapper(self, column, mostly=None, output_format=None, *args, **kwargs):

            if output_format is None:
                output_format = self.default_expectation_args["output_format"]

            series = self[column]
            boolean_mapped_null_values = series.isnull()

            element_count = int(len(series))
            nonnull_values = series[boolean_mapped_null_values==False]
            nonnull_count = (boolean_mapped_null_values==False).sum()

            boolean_mapped_success_values = func(self, nonnull_values, *args, **kwargs)
            success_count = boolean_mapped_success_values.sum()

            exception_list = list(series[(boolean_mapped_success_values==False)&(boolean_mapped_null_values==False)])
            exception_index_list = list(series[(boolean_mapped_success_values==False)&(boolean_mapped_null_values==False)].index)
            exception_count = len(exception_list)

            success, percent_success = self.calc_map_expectation_success(success_count, nonnull_count, exception_count, mostly)

            return_obj = self.format_column_map_output(
                output_format, success,
                element_count,
                nonnull_values, nonnull_count,
                boolean_mapped_success_values, success_count,
                exception_list, exception_index_list
            )

            return return_obj

        inner_wrapper.__name__ = func.__name__
        inner_wrapper.__doc__ = func.__doc__
        return inner_wrapper


    @classmethod
    def column_aggregate_expectation(cls, func):
        """
        The column_aggregate_expectation decorator handles boilerplate issues surrounding computing aggregate measures
        from all nonnull values in a column.

        NOTE: The MetaPandasDataSet implementation replaces the "column" parameter supplied by the user with a pandas
        Series object containing the actual column from the relevant pandas dataframe. This simplifies the implementing
        expectation logic while preserving the standard DataSet signature and expected behavior.

        Further, the column_aggregate_expectation provides a unique set of output_format options.
        """
        @cls.expectation(inspect.getargspec(func)[0][1:])
        @wraps(func)
        def inner_wrapper(self, column, output_format = None, *args, **kwargs):

            if output_format is None:
                output_format = self.default_expectation_args["output_format"]

            series = self[column]
            null_indexes = series.isnull()

            nonnull_values = series[null_indexes == False]
            nonnull_count = (null_indexes == False).sum()

            result_obj = func(self, nonnull_values, *args, **kwargs)

            #!!! This would be the right place to validate result_obj
            #!!! It should contain:
            #!!!    success: bool
            #!!!    true_value: int or float
            #!!!    summary_obj: json-serializable dict

            if output_format in ["BASIC", "COMPLETE"]:
                return_obj = {
                    "success" : bool(result_obj["success"]),
                    "true_value" : result_obj["true_value"],
                }

            elif (output_format == "SUMMARY"):
                return_obj = {
                    "success" : bool(result_obj["success"]),
                    "true_value" : result_obj["true_value"],
                    "summary_obj" : result_obj["summary_obj"]
                }

            elif output_format=="BOOLEAN_ONLY":
                return_obj = bool(result_obj["success"])

            else:
                print ("Warning: Unknown output_format %s. Defaulting to BASIC." % (output_format,))
                return_obj = {
                    "success" : bool(result_obj["success"]),
                    "true_value" : result_obj["true_value"],
                }

            return return_obj

        return inner_wrapper

    ##### Output generation #####

    def format_column_map_output(self,
        output_format, success,
        element_count,
        nonnull_values, nonnull_count,
        boolean_mapped_success_values, success_count,
        exception_list, exception_index_list
    ):
        if output_format=="BOOLEAN_ONLY":
            return_obj = success

        elif output_format=="BASIC":
            exception_count = len(exception_list)

            return_obj = {
                "success": success,
                "summary_obj": {
                    "partial_exception_list": exception_list[:20],
                    "exception_count": exception_count,
                    "exception_percent": float(exception_count) / nonnull_count,
                }
            }

        elif output_format == "COMPLETE":
            return_obj = {
                "success": success,
                "exception_list": exception_list,
                "exception_index_list": exception_index_list,
            }

        elif output_format == "SUMMARY":
            # element_count = int(len(series))
            missing_count = element_count-int(len(nonnull_values))#int(null_indexes.sum())
            exception_count = len(exception_list)

            exception_value_series = pd.Series(exception_list).value_counts()
            exception_counts = dict(zip(
                list(exception_value_series.index),
                list(exception_value_series.values),
            ))

            if element_count > 0:
                missing_percent = float(missing_count) / element_count

                if nonnull_count > 0:
                    exception_percent = float(exception_count) / element_count
                    exception_percent_nonmissing = float(exception_count) / nonnull_count

            else:
                missing_percent = None
                nonmissing_count = None
                exception_percent = None
                exception_percent_nonmissing = None


            return_obj = {
                "success" : success,
                "exception_list" : exception_list,
                "exception_index_list": exception_index_list,
                "summary_obj" : {
                    "element_count" : element_count,
                    "missing_count" : missing_count,
                    "missing_percent" : missing_percent,
                    "exception_count" : exception_count,
                    "exception_percent": exception_percent,
                    "exception_percent_nonmissing": exception_percent_nonmissing,
                    "exception_counts": exception_counts,
                }
            }

        else:
            print ("Warning: Unknown output_format %s. Defaulting to BASIC." % (output_format,))
            return_obj = {
                "success" : success,
                "exception_list" : exception_list,
            }

        return return_obj

    def calc_map_expectation_success(self, success_count, nonnull_count, exception_count, mostly):
        if nonnull_count > 0:
            percent_success = float(success_count)/nonnull_count

            if mostly:
                success = percent_success >= mostly

            else:
                success = exception_count == 0

        else:
            success = True
            percent_success = None

        return success, percent_success


class PandasDataSet(MetaPandasDataSet, pd.DataFrame):

    def __init__(self, *args, **kwargs):
        super(PandasDataSet, self).__init__(*args, **kwargs)

    ### Expectation methods ###

    @DataSet.expectation(['column'])
    def expect_column_to_exist(self, column):
        if column in self:
            return {
                "success" : True
            }
        else:
            return {
                "success": False
            }

    @DataSet.expectation(['min_value', 'max_value'])
    def expect_table_row_count_to_be_between(self, min_value, max_value):

        outcome = False
        if self.shape[0] >= min_value and self.shape[0] <= max_value:
            outcome = True

        return {
            'success':outcome,
            'true_value': self.shape[0]
        }


    @DataSet.expectation(['value'])
    def expect_table_row_count_to_equal(self, value):

        outcome = False
        if self.shape[0] == value:
            outcome = True

        return {
            'success':outcome,
            'true_value':self.shape[0]
        }


    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_be_unique(self, column):
        dupes = set(column[column.duplicated()])
        return column.map(lambda x: x not in dupes)

    @DataSet.expectation(['column', 'mostly', 'output_format'])
    def expect_column_values_to_not_be_null(self, column, mostly=None, output_format=None):
        if output_format == None:
            output_format = self.default_expectation_args["output_format"]

        series = self[column]
        boolean_mapped_null_values = series.isnull()

        element_count = int(len(series))
        nonnull_values = series[boolean_mapped_null_values==False]
        nonnull_count = (boolean_mapped_null_values==False).sum()

        boolean_mapped_success_values = boolean_mapped_null_values==False
        success_count = boolean_mapped_success_values.sum()

        exception_list = [None for i in list(series[(boolean_mapped_success_values==False)])]
        exception_index_list = list(series[(boolean_mapped_success_values==False)].index)
        exception_count = len(exception_list)

        # Pass element_count instead of nonnull_count, because that's the right denominator for this expectation
        success, percent_success = self.calc_map_expectation_success(success_count, element_count, exception_count, mostly)

        return_obj = self.format_column_map_output(
            output_format, success,
            element_count,
            nonnull_values, nonnull_count,
            boolean_mapped_success_values, success_count,
            exception_list, exception_index_list
        )

        return return_obj

    @DataSet.expectation(['column', 'mostly', 'output_format'])
    def expect_column_values_to_be_null(self, column, mostly=None, output_format=None):
        if output_format == None:
            output_format = self.default_expectation_args["output_format"]

        series = self[column]
        boolean_mapped_null_values = series.isnull()

        element_count = int(len(series))
        nonnull_values = series[boolean_mapped_null_values==False]
        nonnull_count = (boolean_mapped_null_values==False).sum()

        boolean_mapped_success_values = boolean_mapped_null_values
        success_count = boolean_mapped_success_values.sum()

        exception_list = list(series[(boolean_mapped_success_values==False)])
        exception_index_list = list(series[(boolean_mapped_success_values==False)].index)
        exception_count = len(exception_list)

        # Pass element_count instead of nonnull_count, because that's the right denominator for this expectation
        success, percent_success = self.calc_map_expectation_success(success_count, element_count, exception_count, mostly)

        return_obj = self.format_column_map_output(
            output_format, success,
            element_count,
            nonnull_values, nonnull_count,
            boolean_mapped_success_values, success_count,
            exception_list, exception_index_list
        )

        return return_obj

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_be_of_type(self, column, type_, target_datasource="numpy"):
        python_avro_types = {
                "null":type(None),
                "boolean":bool,
                "int":int,
                "long":int,
                "float":float,
                "double":float,
                "bytes":bytes,
                "string":str
                }

        numpy_avro_types = {
                "null":np.nan,
                "boolean":np.bool_,
                "int":np.int64,
                "long":np.longdouble,
                "float":np.float_,
                "double":np.longdouble,
                "bytes":np.bytes_,
                "string":np.string_
                }

        datasource = {"python":python_avro_types, "numpy":numpy_avro_types}

        target_type = datasource[target_datasource][type_]
        result = column.map(lambda x: type(x) == target_type)

        return result

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_be_in_type_list(self, column, type_, target_datasource="numpy"):

        python_avro_types = {
                "null":type(None),
                "boolean":bool,
                "int":int,
                "long":int,
                "float":float,
                "double":float,
                "bytes":bytes,
                "string":str
                }

        numpy_avro_types = {
                "null":np.nan,
                "boolean":np.bool_,
                "int":np.int64,
                "long":np.longdouble,
                "float":np.float_,
                "double":np.longdouble,
                "bytes":np.bytes_,
                "string":np.string_
                }

        datasource = {"python":python_avro_types, "numpy":numpy_avro_types}

        target_type_list = [datasource[target_datasource][t] for t in type_]
        result = column.map(lambda x: type(x) in target_type_list)

        return result


    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_be_in_set(self, column, value_set=None):
        return column.map(lambda x: x in value_set)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_not_be_in_set(self, column, value_set=None):
        return column.map(lambda x: x not in value_set)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_be_between(self, column, min_value=None, max_value=None):

        def is_between(val):
            # TODO Might be worth explicitly defining comparisons between types (for example, between strings and ints).
            # Ensure types can be compared since some types in Python 3 cannot be logically compared.
            if type(val) == None:
                return False
            else:
                try:

                    if min_value != None and max_value != None:
                        return (min_value <= val) and (val <= max_value)

                    elif min_value == None and max_value != None:
                        return (val <= max_value)

                    elif min_value != None and max_value == None:
                        return (min_value <= val)

                    else:
                        raise ValueError("min_value and max_value cannot both be None")
                except:
                    return False

        return column.map(is_between)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_value_lengths_to_be_between(self, column, min_value=None, max_value=None):
        #TODO should the mapping function raise the error or should the decorator?
        def length_is_between(val):

            if min_value != None and max_value != None:
                try:
                    return len(val) >= min_value and len(val) <= max_value
                except:
                    return False

            elif min_value == None and max_value != None:
                return len(val) <= max_value

            elif min_value != None and max_value == None:
                return len(val) >= min_value

            else:
                raise ValueError("Undefined interval: min_value and max_value are both None")

        return column.map(length_is_between)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_value_lengths_to_equal(self, column, value):
        return column.map(lambda x : len(x) == value)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_match_regex(self, column, regex):
        return column.map(
            lambda x: re.findall(regex, str(x)) != []
        )

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_not_match_regex(self, column, regex):
        return column.map(lambda x: re.findall(regex, str(x)) == [])

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_match_regex_list(self, column, regex_list):

        def match_in_list(val):
            if any(re.match(regex, str(val)) for regex in regex_list):
                return True
            else:
                return False

        return column.map(match_in_list)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_match_strftime_format(self, column, strftime_format):
        ## Below is a simple validation that the provided format can both format and parse a datetime object.
        ## %D is an example of a format that can format but not parse, e.g.
        try:
            datetime.strptime(datetime.strftime(datetime.now(), strftime_format), strftime_format)
        except ValueError as e:
            raise ValueError("Unable to use provided format. " + e.message)

        def is_parseable_by_format(val):
            try:
                # Note explicit cast of val to str type
                datetime.strptime(str(val), strftime_format)
                return True
            except ValueError as e:
                return False

        return column.map(is_parseable_by_format)

        #TODO Add the following to the decorator as a preliminary check.
        #if (not (column in self)):
        #    raise LookupError("The specified column does not exist.")

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_be_dateutil_parseable(self, column):
        def is_parseable(val):
            try:
                parse(val)
                return True
            except:
                return False

        return column.map(is_parseable)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_be_json_parseable(self, column):
        def is_json(val):
            try:
                json.loads(val)
                return True
            except:
                return False

        return column.map(is_json)

    @MetaPandasDataSet.column_map_expectation
    def expect_column_values_to_match_json_schema(self):
        raise NotImplementedError("Under development")

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_mean_to_be_between(self, column, min_value, max_value):

        #!!! Does not raise an error if both min_value and max_value are None.
        column_mean = column.mean()

        return {
            "success": (
                ((min_value <= column_mean) or (min_value is None)) and
                ((column_mean <= max_value) or (max_value is None))
            ),
            "true_value": column_mean,
            "summary_obj": {}
        }

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_median_to_be_between(self, column, min_value, max_value):

        #!!! Does not raise an error if both min_value and max_value are None.
        column_median = column.median()

        return {
            "success": (
                ((min_value <= column_median) or (min_value or None)) and
                ((column_median <= max_value) or (max_value or None))
            ),
            "true_value": column_median,
            "summary_obj": {}
        }

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_stdev_to_be_between(self, column, min_value, max_value):

        #!!! Does not raise an error if both min_value and max_value are None.
        column_stdev = column.std()

        return {
            "success": (
                ((min_value <= column_stdev) or (min_value is None)) and
                ((column_stdev <= max_value) or (max_value is None))
            ),
            "true_value": column_stdev,
            "summary_obj": {}
        }

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_unique_value_count_to_be_between(self, column, min_value=None, max_value=None):
        unique_value_count = column.value_counts().shape[0]

        return {
            "success" : (
                ((min_value <= unique_value_count) or (min_value is None)) and
                ((unique_value_count <= max_value) or (max_value is None))
            ),
            "true_value": unique_value_count,
            "summary_obj": {}
        }

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_proportion_of_unique_values_to_be_between(self, series, min_value=0, max_value=1):
        unique_value_count = series.value_counts().shape[0]
        total_value_count = int(len(series))#.notnull().sum()

        if total_value_count > 0:
            proportion_unique = float(unique_value_count) / total_value_count
        else:
            proportion_unique = None

        return {
            "success": (
                ((min_value <= proportion_unique) or (min_value is None)) and
                ((proportion_unique <= max_value) or (max_value is None))
            ),
            "true_value": proportion_unique,
            "summary_obj": {}
        }

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_chisquare_test_p_value_greater_than(self, column, partition_object=None, p=0.05):
        if not is_valid_partition_object(partition_object):
            raise ValueError("Invalid partition object.")

        expected_column = pd.Series(partition_object['weights'], index=partition_object['partition'], name='expected') * len(column)
        observed_frequencies = column.value_counts()
        # Join along the indicies to ensure we have values
        test_df = pd.concat([expected_column, observed_frequencies], axis = 1).fillna(0)
        test_result = stats.chisquare(test_df[column.name], test_df['expected'])[1]

        result_obj = {
                "success": test_result > p,
                "true_value": test_result,
                "summary_obj": {}
            }

        return result_obj

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_bootstrapped_ks_test_p_value_greater_than(self, column, partition_object=None, p=0.05, bootstrap_samples=0):
        if not is_valid_partition_object(partition_object):
            raise ValueError("Invalid partition object.")

        estimated_cdf = lambda x: np.interp(x, partition_object['partition'], np.append(np.array([0]), np.cumsum(partition_object['weights'])))

        if (bootstrap_samples == 0):
            #bootstrap_samples = min(1000, int (len(not_null_values) / len(partition_object['weights'])))
            bootstrap_samples = 1000

        results = [ stats.kstest(
                        np.random.choice(column, size=len(partition_object['weights']), replace=True),
                        estimated_cdf)[1]
                    for k in range(bootstrap_samples)
                  ]

        test_result = np.mean(results)

        result_obj = {
                "success" : test_result > p,
                "true_value": test_result,
                "summary_obj": {
                    "bootstrap_samples": bootstrap_samples
                }
            }

        return result_obj

    @MetaPandasDataSet.column_aggregate_expectation
    def expect_column_kl_divergence_less_than(self, column, partition_object=None, threshold=None):
        if not is_valid_partition_object(partition_object):
            raise ValueError("Invalid partition object.")

        if not (isinstance(threshold, float) and (threshold >= 0)):
            raise ValueError("Threshold must be specified, greater than or equal to zero.")

        # If the data expected to be discrete, build a column
        if (len(partition_object['weights']) == len(partition_object['partition'])):
            observed_frequencies = column.value_counts()
            pk = observed_frequencies / (1.* len(column))
        else:
            partition_object = remove_empty_intervals(partition_object)
            hist, bin_edges = np.histogram(column, partition_object['partition'], density=False)
            pk = hist / (1.* len(column))

        kl_divergence = stats.entropy(pk, partition_object['weights'])

        result_obj = {
                "success": kl_divergence <= threshold,
                "true_value": kl_divergence,
                "summary_obj": {}
            }

        return result_obj
