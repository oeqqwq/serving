#! python3

# Copyright 2023 Ant Group Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import json
import os
import time
from typing import Any, Dict, List

import pyarrow as pa

from secretflow_serving_lib.graph_pb2 import (
    DispatchType,
    ExecutionDef,
    GraphDef,
    NodeDef,
    RuntimeConfig,
)
from secretflow_serving_lib.link_function_pb2 import LinkFunctionType

from test_common import (
    TestCase,
    TestConfig,
    PartyConfig,
    make_processing_node_def,
    make_dot_product_node_def,
    make_merge_y_node_def,
    make_tree_select_node_def,
    make_tree_merge_node_def,
    make_tree_ensemble_predict_node_def,
    global_ip_config,
    ProcRunGuard,
    build_predict_cmd,
)


class MockFeatureTest(TestCase):
    def __init__(
        self,
        service_id: str,
        path: str,
        nodes: Dict[str, List[NodeDef]],
        executions: Dict[str, List[ExecutionDef]],
        feature_mappings: Dict[str, Dict] = None,
        specific_party: str = None,
    ):
        super().__init__(path)

        # build config
        ip_config_idx = 0
        party_configs = []
        for party, node_list in nodes.items():
            graph = GraphDef(
                version="0.0.1",
                node_list=node_list,
                execution_list=executions[party],
            )
            party_configs.append(
                PartyConfig(
                    id=party,
                    feature_mapping=(
                        {} if not feature_mappings else feature_mappings[party]
                    ),
                    **global_ip_config(ip_config_idx),
                    channel_protocol="baidu_std",
                    model_id="integration_model",
                    graph_def=graph,
                    query_datas=["a", "b", "c", "d"],
                )
            )
            ip_config_idx += 1

        self.config = TestConfig(
            path,
            service_spec_id=service_id,
            party_config=party_configs,
            specific_party=specific_party,
        )

    def test(self, config: TestConfig):
        config.dump_config()
        config.exec_start_server_scripts()
        for party in config.get_party_ids():
            if config.specific_party and config.specific_party != party:
                continue
            res = config.exec_curl_request_scripts(party)
            out = res.stdout.decode()
            print("Result: ", out)
            res = json.loads(out)
            assert res["status"]["code"] == 1, "return status code is not OK(1)"
            assert len(res["results"]) == len(
                config.party_config[0].query_datas
            ), f"result rows({len(res['results'])}) not equal to query_data({len(config.party_config[0].query_datas)})"

            model_info = config.exec_get_model_info_request_scripts(party)
            out = model_info.stdout.decode()
            print("Model info: ", out)
            res = json.loads(out)
            assert res["status"]["code"] == 1, "return status code is not OK(1)"

    def get_config(self, path: str) -> TestConfig:
        return self.config


class PredefinedErrorTest(TestCase):
    def get_config(self, path: str) -> TestConfig:
        dot_node_alice = make_dot_product_node_def(
            name="node_dot_product",
            parents=[],
            weight_dict={"x1": 1.0, "x2": 2.0, "x3": 3.0},
            input_types=["DT_FLOAT", "DT_DOUBLE", "DT_INT32"],
            output_col_name="y",
            intercept=0,
        )
        dot_node_bob = make_dot_product_node_def(
            name="node_dot_product",
            parents=[],
            weight_dict={"x1": -1.0, "x2": -2.0, "x3": -3.0},
            input_types=["DT_FLOAT", "DT_DOUBLE", "DT_INT32"],
            output_col_name="y",
            intercept=0,
        )
        merge_y_node = make_merge_y_node_def(
            "node_merge_y",
            ["node_dot_product"],
            LinkFunctionType.LF_IDENTITY,
            input_col_name="y",
            output_col_name="score",
            yhat_scale=1.0,
        )
        execution_1 = ExecutionDef(
            nodes=["node_dot_product"],
            config=RuntimeConfig(dispatch_type=DispatchType.DP_ALL, session_run=False),
        )
        execution_2 = ExecutionDef(
            nodes=["node_merge_y"],
            config=RuntimeConfig(
                dispatch_type=DispatchType.DP_ANYONE, session_run=False
            ),
        )

        alice_graph = GraphDef(
            version="0.0.1",
            node_list=[dot_node_alice, merge_y_node],
            execution_list=[execution_1, execution_2],
        )
        bob_graph = GraphDef(
            version="0.0.1",
            node_list=[dot_node_bob, merge_y_node],
            execution_list=[execution_1, execution_2],
        )

        alice_config = PartyConfig(
            id="alice",
            feature_mapping={},
            **global_ip_config(0),
            channel_protocol="baidu_std",
            model_id="integration_model",
            graph_def=alice_graph,
            query_datas=["a", "a", "a"],  # only length matters
        )
        bob_config = PartyConfig(
            id="bob",
            feature_mapping={},
            **global_ip_config(1),
            channel_protocol="baidu_std",
            model_id="integration_model",
            graph_def=bob_graph,
            query_datas=["a", "a", "a"],  # only length matters
        )
        return TestConfig(
            path,
            service_spec_id="integration_test",
            party_config=[alice_config, bob_config],
            predefined_features={
                "x1": [1.0, 2.0, 3.4],
                "x2": [6.0, 7.0, 8.0],
                "x3": [-9, -10, -11],
            },
            predefined_types={
                "x1": "FIELD_FLOAT",
                "x2": "FIELD_DOUBLE",
                "x3": "FIELD_INT32",
            },
        )

    def test(self, config):
        new_config = {}
        for k, v in config.predefined_features.items():
            v.append(9.9)
            new_config[k] = v
        config.predefined_features = new_config
        config.dump_config()
        config.exec_start_server_scripts()

        for party in config.get_party_ids():
            res = config.exec_curl_request_scripts(party)
            out = res.stdout.decode()
            print("Result: ", out)
            res = json.loads(out)
            assert (
                res["status"]["code"] != 1
            ), f'return status code({res["status"]["code"]}) should not be OK(1)'


class PredefineTest(PredefinedErrorTest):
    def test(self, config):
        config.dump_config()
        config.exec_start_server_scripts()
        results = []
        for party in config.get_party_ids():
            res = config.exec_curl_request_scripts(party)
            out = res.stdout.decode()
            print("Result: ", out)
            res = json.loads(out)
            assert (
                res["status"]["code"] == 1
            ), f'return status code({res["status"]["code"]}) is not OK(1)'
            assert len(res["results"]) == len(
                config.party_config[0].query_datas
            ), f"result rows({len(res['results'])}) not equal to query_data({len(config.party_config[0].query_datas)})"
            results.append(res)
        # std::rand in MockAdapter start with same seed at both sides
        for a_score, b_score in zip(results[0]["results"], results[1]["results"]):
            assert a_score["scores"][0]["value"] + b_score["scores"][0]["value"] == 0


class CsvTest(TestCase):
    def __init__(self, path: str, use_http_feature_source: bool = False):
        super().__init__(path)
        self.use_http_feature_source = use_http_feature_source

    def get_config(self, path: str):
        dot_node_alice = make_dot_product_node_def(
            name="node_dot_product",
            parents=[],
            weight_dict={"x1": 1.0, "x2": 2.0},
            input_types=["DT_INT8", "DT_UINT8"],
            output_col_name="y",
            intercept=0,
        )
        dot_node_bob = make_dot_product_node_def(
            name="node_dot_product",
            parents=[],
            weight_dict={"x1": -1.0, "x2": -2.0},
            input_types=["DT_INT16", "DT_UINT16"],
            output_col_name="y",
            intercept=0,
        )
        merge_y_node = make_merge_y_node_def(
            "node_merge_y",
            ["node_dot_product"],
            LinkFunctionType.LF_IDENTITY,
            input_col_name="y",
            output_col_name="score",
            yhat_scale=1.0,
        )

        execution_1 = ExecutionDef(
            nodes=["node_dot_product"],
            config=RuntimeConfig(dispatch_type=DispatchType.DP_ALL, session_run=False),
        )
        execution_2 = ExecutionDef(
            nodes=["node_merge_y"],
            config=RuntimeConfig(
                dispatch_type=DispatchType.DP_ANYONE, session_run=False
            ),
        )

        alice_graph = GraphDef(
            version="0.0.1",
            node_list=[dot_node_alice, merge_y_node],
            execution_list=[execution_1, execution_2],
        )
        bob_graph = GraphDef(
            version="0.0.1",
            node_list=[dot_node_bob, merge_y_node],
            execution_list=[execution_1, execution_2],
        )

        alice_config = PartyConfig(
            id="alice",
            feature_mapping={"v1": "x1", "v2": "x2"},
            **global_ip_config(0),
            channel_protocol="baidu_std",
            model_id="integration_model",
            graph_def=alice_graph,
            query_datas=["a", "b", "c"],  # Corresponds to the id column in csv
            csv_dict={
                "id": ["a", "b", "c", "d"],
                "v1": [1, 2, 3, 4],
                "v2": [5, 6, 7, 8],
            },
            use_http_feature_source=self.use_http_feature_source,
        )
        bob_config = PartyConfig(
            id="bob",
            feature_mapping={"vv2": "x2", "vv3": "x1"},
            **global_ip_config(1),
            channel_protocol="baidu_std",
            model_id="integration_model",
            graph_def=bob_graph,
            query_datas=["a", "b", "c"],  # Corresponds to the id column in csv
            csv_dict={
                "id": ["b", "a", "c"],
                "vv3": [2, 1, 3],
                "vv2": [6, 5, 7],
            },
            use_http_feature_source=self.use_http_feature_source,
        )
        return TestConfig(
            path,
            service_spec_id="integration_test",
            party_config=[alice_config, bob_config],
        )

    def test(self, config):
        config.dump_config()
        config.exec_start_server_scripts()

        for party in config.get_party_ids():
            res = config.exec_curl_request_scripts(party)
            out = res.stdout.decode()
            print("Result: ", out)
            res = json.loads(out)
            assert (
                res["status"]["code"] == 1
            ), f'return status code({res["status"]["code"]}) is not OK(1)'
            assert len(res["results"]) == len(
                config.party_config[0].query_datas
            ), f"result rows({len(res['results'])}) not equal to query_data({len(config.party_config[0].query_datas)})"
            for score in res["results"]:
                assert score["scores"][0]["value"] == 0, "result should be 0"


class SpecificTest(TestCase):
    def get_config(self, path: str):
        dot_node_alice = make_dot_product_node_def(
            name="node_dot_product",
            parents=[],
            weight_dict={"x1": 1.0, "x2": 2.0},
            input_types=["DT_DOUBLE", "DT_DOUBLE"],
            output_col_name="y",
            intercept=0,
        )
        dot_node_bob = make_dot_product_node_def(
            name="node_dot_product",
            parents=[],
            weight_dict={"x1": -1.0, "x2": -2.0},
            input_types=["DT_DOUBLE", "DT_DOUBLE"],
            output_col_name="y",
            intercept=0,
        )
        merge_y_node = make_merge_y_node_def(
            "node_merge_y",
            ["node_dot_product"],
            LinkFunctionType.LF_IDENTITY,
            input_col_name="y",
            output_col_name="score",
            yhat_scale=1.0,
        )
        dot_node_specific_1 = make_dot_product_node_def(
            name="node_dot_product_spec",
            parents=["node_merge_y"],
            weight_dict={"score": 1.0},
            input_types=["DT_DOUBLE"],
            output_col_name="y",
            intercept=1234.0,
        )
        dot_node_specific_2 = make_dot_product_node_def(
            name="node_dot_product_spec",
            parents=["node_merge_y"],
            input_types=["DT_DOUBLE"],
            weight_dict={"score": 1.0},
            output_col_name="y",
            intercept=2468.0,
        )
        merge_y_node_res = make_merge_y_node_def(
            "node_merge_y_res",
            ["node_dot_product_spec"],
            LinkFunctionType.LF_IDENTITY,
            input_col_name="y",
            output_col_name="score",
            yhat_scale=1.0,
        )
        execution_1 = ExecutionDef(
            nodes=["node_dot_product"],
            config=RuntimeConfig(dispatch_type=DispatchType.DP_ALL, session_run=False),
        )
        execution_2_alice = ExecutionDef(
            nodes=["node_merge_y", "node_dot_product_spec", "node_merge_y_res"],
            config=RuntimeConfig(
                dispatch_type=DispatchType.DP_SPECIFIED,
                session_run=False,
                specific_flag=True,
            ),
        )

        execution_2_bob = ExecutionDef(
            nodes=["node_merge_y", "node_dot_product_spec", "node_merge_y_res"],
            config=RuntimeConfig(
                dispatch_type=DispatchType.DP_SPECIFIED, session_run=False
            ),
        )

        alice_graph = GraphDef(
            version="0.0.1",
            node_list=[
                dot_node_alice,
                merge_y_node,
                dot_node_specific_1,
                merge_y_node_res,
            ],
            execution_list=[
                execution_1,
                execution_2_alice,
            ],
        )
        bob_graph = GraphDef(
            version="0.0.1",
            node_list=[
                dot_node_bob,
                merge_y_node,
                dot_node_specific_2,
                merge_y_node_res,
            ],
            execution_list=[execution_1, execution_2_bob],
        )

        alice_config = PartyConfig(
            id="alice",
            feature_mapping={"v1": "x1", "v2": "x2"},
            **global_ip_config(0),
            channel_protocol="baidu_std",
            model_id="integration_model",
            graph_def=alice_graph,
            query_datas=["a", "b", "c"],  # Corresponds to the id column in csv
            csv_dict={
                "id": ["a", "b", "c", "d"],
                "v1": [1.0, 2.0, 3.0, 4.0],
                "v2": [5.0, 6.0, 7.0, 8.0],
            },
        )
        bob_config = PartyConfig(
            id="bob",
            feature_mapping={"vv2": "x2", "vv3": "x1"},
            **global_ip_config(1),
            channel_protocol="baidu_std",
            model_id="integration_model",
            graph_def=bob_graph,
            query_datas=["a", "b", "c"],  # Corresponds to the id column in csv
            csv_dict={
                "id": ["a", "b", "c"],
                "vv3": [1.0, 2.0, 3.0],
                "vv2": [5.0, 6.0, 7.0],
            },
        )
        return TestConfig(
            path,
            service_spec_id="integration_test",
            party_config=[alice_config, bob_config],
        )

    def test(self, config):
        config.dump_config()
        config.exec_start_server_scripts(2)

        for party in config.get_party_ids():
            res = config.exec_curl_request_scripts(party)
            out = res.stdout.decode()
            print("Result: ", out)
            res = json.loads(out)
            assert (
                res["status"]["code"] == 1
            ), f'return status code({res["status"]["code"]}) is not OK(1)'
            assert len(res["results"]) == len(
                config.party_config[0].query_datas
            ), f"result rows({len(res['results'])}) not equal to query_data({len(config.party_config[0].query_datas)})"
            for score in res["results"]:
                assert (
                    score["scores"][0]["value"] == 1234.0
                ), f'result should be 0, got: {score["scores"][0]["value"]}'


class ExampleTest(ProcRunGuard):
    def __init__(self, base_path: str):
        super().__init__()

        self.parties = ["alice", "bob"]
        self.serving_cmd_dict = {}
        self.serving_config_dict = {}

        self.trace_configs = {}

        self.trace_files = {}
        for p in self.parties:
            party_base_path = os.path.join(base_path, p)
            serving_config_file = os.path.join(party_base_path, "serving.config")
            logging_config_file = os.path.join(party_base_path, "logging.config")
            trace_config_file = os.path.join(party_base_path, "trace.config")

            self.trace_configs[p] = trace_config_file

            self.serving_cmd_dict[p] = (
                f"./bazel-bin/secretflow_serving/server/secretflow_serving --serving_config_file={serving_config_file} --logging_config_file={logging_config_file} --trace_config_file={trace_config_file}"
            )

            with open(serving_config_file, "r") as file:
                serving_conf = json.load(file)
                self.serving_config_dict[p] = serving_conf

    def exec(self):
        try:
            # start serving
            for p in self.parties:
                self.run_cmd(self.serving_cmd_dict[p], True)

            time.sleep(10)

            body_dict = {
                "service_spec": {
                    "id": "test_service_id",
                },
                "fs_params": {
                    "alice": {"query_datas": ["a"]},
                    "bob": {"query_datas": ["a"]},
                },
            }

            trace_id_prefix = "1234567890abcdef1234567890abcde"
            self.span_id = "1234567890abcdef"
            self.trace_id_map = {}
            parties_index = 0
            # make request
            for p in self.parties:
                trace_id = f"{trace_id_prefix}{parties_index}"
                self.trace_id_map[p] = trace_id
                parties_index += 1
                res = self.run_cmd(
                    build_predict_cmd(
                        "127.0.0.1",
                        self.serving_config_dict[p]['serverConf']['servicePort'],
                        json.dumps(body_dict),
                        {'X-B3-TraceId': trace_id, 'X-B3-SpanId': self.span_id},
                    )
                )
                out = res.stdout.decode()
                print("Predict Result: ", out)
                res = json.loads(out)
                assert (
                    res["status"]["code"] == 1
                ), f'return status code({res["status"]["code"]}) should be OK(1)'

            # wait trace flush
            time.sleep(10)

            # check trace log
            self.check_trace_log()

        finally:
            self.cleanup_sub_procs()
            self.cleanup_trace_files()

    def cleanup_trace_files(self):
        for p in self.parties:
            trace_config_file = self.trace_configs[p]
            with open(trace_config_file, "r") as f:
                trace_config = json.load(f)
                trace_dir = trace_config["traceLogConf"]["traceLogPath"]
            if os.path.exists(trace_dir):
                os.remove(trace_dir)

    def check_trace_log(self):
        def decode_bytes(proto_bytes):
            import base64

            return base64.b16encode(base64.b64decode(proto_bytes)).lower().decode()

        def get_spans_from_trace_file(trace_filename):
            spans = []
            with open(trace_filename, 'r') as trace_file:
                for line in trace_file:
                    start_index = line.find('{')
                    if start_index == -1:
                        continue
                    resource_span = json.loads(line[start_index:])
                    for scopeSpan in resource_span['scopeSpans']:
                        spans.extend(scopeSpan['spans'])
            return spans

        stub_span_id_dict = {}
        service_span_id_dict = {}

        for p, config in self.trace_configs.items():
            stub_span_id_dict[p] = set()
            service_span_id_dict[p] = set()

            with open(config, "r") as f:
                trace_config = json.load(f)
                trace_dir = trace_config["traceLogConf"]["traceLogPath"]
            spans = get_spans_from_trace_file(trace_dir)
            intrest_span_found = False
            for span in spans:
                if span['name'] == "PredictionService/Predict":
                    assert self.trace_id_map[p] == decode_bytes(
                        span['traceId']
                    ), f"trace id mismatch, expected: {self.trace_id_map[p]}, actual: {decode_bytes(span['traceId'])}"
                    assert self.span_id == decode_bytes(
                        span['parentSpanId']
                    ), f"parent span id mismatch, expected: {self.span_id}, actual: {decode_bytes(span['parentSpanId'])}"
                    intrest_span_found = True
                if (
                    span['name'].startswith("ExecutionService")
                    and span['kind'] == "SPAN_KIND_SERVER"
                ):
                    service_span_id_dict[p].add(decode_bytes(span['parentSpanId']))
                if (
                    span['name'].startswith("ExecutionService")
                    and span['kind'] == "SPAN_KIND_CLIENT"
                ):
                    stub_span_id_dict[p].add(decode_bytes(span['spanId']))
            assert intrest_span_found
        assert (
            service_span_id_dict["alice"] == stub_span_id_dict["bob"]
        ), f"execution parent span id mismatch, expected: {service_span_id_dict['alice']}, actual: {stub_span_id_dict['bob']}"

        assert (
            service_span_id_dict["bob"] == stub_span_id_dict["alice"]
        ), f"execution parent span id mismatch, expected: {service_span_id_dict['bob']}, actual: {stub_span_id_dict['alice']}"


def get_mock_feature_glm_test():
    # glm
    with open(".ci/simple_test/node_processing_alice.json", "rb") as f:
        alice_trace_content = f.read()
    return MockFeatureTest(
        service_id="glm",
        path='model_path',
        nodes={
            "alice": [
                make_processing_node_def(
                    name="node_processing",
                    parents=[],
                    input_schema=pa.schema(
                        [
                            ('a', pa.int32()),
                            ('b', pa.float32()),
                            ('c', pa.utf8()),
                            ('x21', pa.float64()),
                            ('x22', pa.float32()),
                            ('x23', pa.int8()),
                            ('x24', pa.int16()),
                            ('x25', pa.int32()),
                        ]
                    ),
                    output_schema=pa.schema(
                        [
                            ('a_0', pa.int64()),
                            ('a_1', pa.int64()),
                            ('c_0', pa.int64()),
                            ('b_0', pa.int64()),
                            ('x21', pa.float64()),
                            ('x22', pa.float32()),
                            ('x23', pa.int8()),
                            ('x24', pa.int16()),
                            ('x25', pa.int32()),
                        ]
                    ),
                    trace_content=alice_trace_content,
                ),
                make_dot_product_node_def(
                    name="node_dot_product",
                    parents=['node_processing'],
                    weight_dict={
                        "x21": -0.3,
                        "x22": 0.95,
                        "x23": 1.01,
                        "x24": 1.35,
                        "x25": -0.97,
                        "a_0": 1.0,
                        "c_0": 1.0,
                        "b_0": 1.0,
                    },
                    output_col_name="y",
                    input_types=[
                        "DT_DOUBLE",
                        "DT_FLOAT",
                        "DT_INT8",
                        "DT_INT16",
                        "DT_INT32",
                        "DT_INT64",
                        "DT_INT64",
                        "DT_INT64",
                    ],
                    intercept=1.313,
                ),
                make_merge_y_node_def(
                    "node_merge_y",
                    ["node_dot_product"],
                    LinkFunctionType.LF_SIGMOID_RAW,
                    input_col_name="y",
                    output_col_name="score",
                    yhat_scale=1.2,
                ),
            ],
            "bob": [
                # bob run dummy node (no trace)
                make_processing_node_def(
                    name="node_processing",
                    parents=[],
                    input_schema=pa.schema(
                        [
                            ('x6', pa.int64()),
                            ('x7', pa.uint8()),
                            ('x8', pa.uint16()),
                            ('x9', pa.uint32()),
                            ('x10', pa.uint64()),
                        ]
                    ),
                    output_schema=pa.schema(
                        [
                            ('x6', pa.int64()),
                            ('x7', pa.uint8()),
                            ('x8', pa.uint16()),
                            ('x9', pa.uint32()),
                            ('x10', pa.uint64()),
                        ]
                    ),
                ),
                make_dot_product_node_def(
                    name="node_dot_product",
                    parents=['node_processing'],
                    weight_dict={
                        "x6": -0.53,
                        "x7": 0.92,
                        "x8": -0.72,
                        "x9": 0.146,
                        "x10": -0.07,
                    },
                    input_types=[
                        "DT_INT64",
                        "DT_UINT8",
                        "DT_UINT16",
                        "DT_UINT32",
                        "DT_UINT64",
                    ],
                    output_col_name="y",
                ),
                make_merge_y_node_def(
                    "node_merge_y",
                    ["node_dot_product"],
                    LinkFunctionType.LF_SIGMOID_RAW,
                    input_col_name="y",
                    output_col_name="score",
                    yhat_scale=1.2,
                ),
            ],
        },
        executions={
            "alice": [
                ExecutionDef(
                    nodes=["node_processing", "node_dot_product"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=["node_merge_y"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ANYONE, session_run=False
                    ),
                ),
            ],
            "bob": [
                ExecutionDef(
                    nodes=["node_processing", "node_dot_product"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=["node_merge_y"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ANYONE, session_run=False
                    ),
                ),
            ],
        },
        feature_mappings={
            "alice": {
                "a": "a",
                "b": "b",
                "c": "c",
                "v24": "x24",
                "v22": "x22",
                "v21": "x21",
                "v25": "x25",
                "v23": "x23",
            },
            "bob": {
                "v6": "x6",
                "v7": "x7",
                "v8": "x8",
                "v9": "x9",
                "v10": "x10",
            },
        },
    )


def get_mock_feature_sgb_test():
    return MockFeatureTest(
        service_id="sgb",
        path='sgb_model',
        nodes={
            "alice": [
                make_tree_select_node_def(
                    name="node_tree_select_0",
                    parents=[],
                    output_col_name="selects",
                    root_node_id=0,
                    feature_dict={
                        "x1": "DT_FLOAT",
                        "x2": "DT_INT16",
                        "x3": "DT_INT8",
                        "x4": "DT_UINT8",
                        "x5": "DT_DOUBLE",
                        "x6": "DT_INT64",
                        "x7": "DT_INT16",
                        "x8": "DT_FLOAT",
                        "x9": "DT_FLOAT",
                        "x10": "DT_FLOAT",
                    },
                    tree_nodes=[
                        {
                            "nodeId": 0,
                            "lchildId": 1,
                            "rchildId": 2,
                            "isLeaf": False,
                            "splitFeatureIdx": 3,
                            "splitValue": -0.154862225,
                        },
                        {
                            "nodeId": 1,
                            "lchildId": 3,
                            "rchildId": 4,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 2,
                            "lchildId": 5,
                            "rchildId": 6,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 3,
                            "lchildId": 7,
                            "rchildId": 8,
                            "isLeaf": False,
                            "splitFeatureIdx": 2,
                            "splitValue": -0.208345324,
                        },
                        {
                            "nodeId": 4,
                            "lchildId": 9,
                            "rchildId": 10,
                            "isLeaf": False,
                            "splitFeatureIdx": 2,
                            "splitValue": 0.301087976,
                        },
                        {
                            "nodeId": 5,
                            "lchildId": 11,
                            "rchildId": 12,
                            "isLeaf": False,
                            "splitFeatureIdx": 1,
                            "splitValue": -0.300848633,
                        },
                        {
                            "nodeId": 6,
                            "lchildId": 13,
                            "rchildId": 14,
                            "isLeaf": False,
                            "splitFeatureIdx": 2,
                            "splitValue": 0.0800122,
                        },
                        {
                            "nodeId": 7,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                        {
                            "nodeId": 8,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                        {
                            "nodeId": 9,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                        {
                            "nodeId": 10,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                        {
                            "nodeId": 11,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                        {
                            "nodeId": 12,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                        {
                            "nodeId": 13,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                        {
                            "nodeId": 14,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": -1,
                        },
                    ],
                ),
                make_tree_select_node_def(
                    name="node_tree_select_1",
                    parents=[],
                    output_col_name="selects",
                    feature_dict={
                        "x1": "DT_FLOAT",
                        "x2": "DT_INT16",
                        "x3": "DT_INT8",
                        "x4": "DT_UINT8",
                        "x5": "DT_DOUBLE",
                        "x6": "DT_INT64",
                        "x7": "DT_INT16",
                        "x8": "DT_FLOAT",
                        "x9": "DT_FLOAT",
                        "x10": "DT_FLOAT",
                    },
                    root_node_id=0,
                    tree_nodes=[
                        {
                            "nodeId": 0,
                            "lchildId": 1,
                            "rchildId": 2,
                            "isLeaf": False,
                            "splitFeatureIdx": 6,
                            "splitValue": -0.261598617,
                        },
                        {
                            "nodeId": 1,
                            "lchildId": 3,
                            "rchildId": 4,
                            "isLeaf": False,
                            "splitFeatureIdx": 4,
                            "splitValue": -0.0992445946,
                        },
                        {
                            "nodeId": 2,
                            "lchildId": 5,
                            "rchildId": 6,
                            "isLeaf": False,
                            "splitFeatureIdx": 4,
                            "splitValue": 0.3885355,
                        },
                        {
                            "nodeId": 3,
                            "lchildId": 7,
                            "rchildId": 8,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 4,
                            "lchildId": 9,
                            "rchildId": 10,
                            "isLeaf": False,
                            "splitFeatureIdx": 1,
                            "splitValue": 0.149844646,
                        },
                        {
                            "nodeId": 5,
                            "lchildId": 11,
                            "rchildId": 12,
                            "isLeaf": False,
                            "splitFeatureIdx": 1,
                            "splitValue": 0.0529966354,
                        },
                        {
                            "nodeId": 6,
                            "lchildId": 13,
                            "rchildId": 14,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 7,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 8,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 9,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 10,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 11,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 12,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 13,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 14,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                    ],
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_0",
                    ["node_tree_select_0"],
                    input_col_name="selects",
                    output_col_name="weights",
                    leaf_node_weights=[
                        -0.116178043,
                        0.16241236,
                        -0.418656051,
                        -0.0926064253,
                        0.15993154,
                        0.358381808,
                        -0.104386188,
                        0.194736511,
                    ],
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_1",
                    ["node_tree_select_1"],
                    input_col_name="selects",
                    output_col_name="weights",
                    leaf_node_weights=[
                        -0.196025193,
                        0.0978358239,
                        -0.381145447,
                        -0.0979942083,
                        0.117580406,
                        0.302539676,
                        0.171336576,
                        -0.125806138,
                    ],
                ),
                make_tree_ensemble_predict_node_def(
                    "node_tree_ensemble_predict",
                    ["node_tree_merge_0", "node_tree_merge_1"],
                    input_col_name="weights",
                    output_col_name="scores",
                    num_trees=2,
                    func_type='LF_SIGMOID_RAW',
                ),
            ],
            "bob": [
                make_tree_select_node_def(
                    name="node_tree_select_0",
                    parents=[],
                    output_col_name="selects",
                    feature_dict={
                        "x11": "DT_FLOAT",
                        "x12": "DT_INT16",
                        "x13": "DT_INT8",
                        "x14": "DT_UINT8",
                        "x15": "DT_DOUBLE",
                        "x16": "DT_INT64",
                        "x17": "DT_INT16",
                        "x18": "DT_FLOAT",
                        "x19": "DT_FLOAT",
                        "x20": "DT_FLOAT",
                    },
                    root_node_id=0,
                    tree_nodes=[
                        {
                            "nodeId": 0,
                            "lchildId": 1,
                            "rchildId": 2,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 1,
                            "lchildId": 3,
                            "rchildId": 4,
                            "isLeaf": False,
                            "splitFeatureIdx": 7,
                            "splitValue": -0.107344508,
                        },
                        {
                            "nodeId": 2,
                            "lchildId": 5,
                            "rchildId": 6,
                            "isLeaf": False,
                            "splitFeatureIdx": 7,
                            "splitValue": 0.210497797,
                        },
                        {
                            "nodeId": 3,
                            "lchildId": 7,
                            "rchildId": 8,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 4,
                            "lchildId": 9,
                            "rchildId": 10,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 5,
                            "lchildId": 11,
                            "rchildId": 12,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 6,
                            "lchildId": 13,
                            "rchildId": 14,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 7,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 8,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 9,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 10,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 11,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 12,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 13,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 14,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                    ],
                ),
                make_tree_select_node_def(
                    name="node_tree_select_1",
                    parents=[],
                    output_col_name="selects",
                    feature_dict={
                        "x11": "DT_FLOAT",
                        "x12": "DT_INT16",
                        "x13": "DT_INT8",
                        "x14": "DT_UINT8",
                        "x15": "DT_DOUBLE",
                        "x16": "DT_INT64",
                        "x17": "DT_INT16",
                        "x18": "DT_FLOAT",
                        "x19": "DT_FLOAT",
                        "x20": "DT_FLOAT",
                    },
                    root_node_id=0,
                    tree_nodes=[
                        {
                            "nodeId": 0,
                            "lchildId": 1,
                            "rchildId": 2,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 1,
                            "lchildId": 3,
                            "rchildId": 4,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 2,
                            "lchildId": 5,
                            "rchildId": 6,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 3,
                            "lchildId": 7,
                            "rchildId": 8,
                            "isLeaf": False,
                            "splitFeatureIdx": 4,
                            "splitValue": -0.548508525,
                        },
                        {
                            "nodeId": 4,
                            "lchildId": 9,
                            "rchildId": 10,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 5,
                            "lchildId": 11,
                            "rchildId": 12,
                            "isLeaf": False,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 6,
                            "lchildId": 13,
                            "rchildId": 14,
                            "isLeaf": False,
                            "splitFeatureIdx": 9,
                            "splitValue": -0.405750543,
                        },
                        {
                            "nodeId": 7,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 8,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 9,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 10,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 11,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 12,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 13,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 14,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                    ],
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_0",
                    ["node_tree_select_0"],
                    input_col_name="selects",
                    output_col_name="weights",
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_1",
                    ["node_tree_select_1"],
                    input_col_name="selects",
                    output_col_name="weights",
                ),
                make_tree_ensemble_predict_node_def(
                    "node_tree_ensemble_predict",
                    ["node_tree_merge_0", "node_tree_merge_1"],
                    input_col_name="weights",
                    output_col_name="scores",
                    num_trees=2,
                    func_type='LF_SIGMOID_RAW',
                ),
            ],
        },
        executions={
            "alice": [
                ExecutionDef(
                    nodes=["node_tree_select_0", "node_tree_select_1"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=[
                        "node_tree_merge_0",
                        "node_tree_merge_1",
                        "node_tree_ensemble_predict",
                    ],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_SPECIFIED,
                        session_run=False,
                        specific_flag=True,
                    ),
                ),
            ],
            "bob": [
                ExecutionDef(
                    nodes=["node_tree_select_0", "node_tree_select_1"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=[
                        "node_tree_merge_0",
                        "node_tree_merge_1",
                        "node_tree_ensemble_predict",
                    ],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_SPECIFIED, session_run=False
                    ),
                ),
            ],
        },
        specific_party="alice",
    )


def get_sgb_alice_no_feature_test():
    return MockFeatureTest(
        service_id="sgb_bob_no_feature",
        path='sgb_model',
        nodes={
            "alice": [
                make_tree_select_node_def(
                    name="node_tree_select_0",
                    parents=[],
                    output_col_name="selects",
                    root_node_id=0,
                    feature_dict={},
                    tree_nodes=[],
                ),
                make_tree_select_node_def(
                    name="node_tree_select_1",
                    parents=[],
                    output_col_name="selects",
                    feature_dict={},
                    root_node_id=0,
                    tree_nodes=[],
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_0",
                    ["node_tree_select_0"],
                    input_col_name="selects",
                    output_col_name="weights",
                    leaf_node_weights=[
                        -0.116178043,
                        0.16241236,
                        -0.418656051,
                        -0.0926064253,
                        0.15993154,
                        0.358381808,
                        -0.104386188,
                        0.194736511,
                    ],
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_1",
                    ["node_tree_select_1"],
                    input_col_name="selects",
                    output_col_name="weights",
                    leaf_node_weights=[
                        -0.196025193,
                        0.0978358239,
                        -0.381145447,
                        -0.0979942083,
                        0.117580406,
                        0.302539676,
                        0.171336576,
                        -0.125806138,
                    ],
                ),
                make_tree_ensemble_predict_node_def(
                    "node_tree_ensemble_predict",
                    ["node_tree_merge_0", "node_tree_merge_1"],
                    input_col_name="weights",
                    output_col_name="scores",
                    num_trees=2,
                    func_type='LF_SIGMOID_RAW',
                ),
            ],
            "bob": [
                make_tree_select_node_def(
                    name="node_tree_select_0",
                    parents=[],
                    output_col_name="selects",
                    feature_dict={
                        "x11": "DT_FLOAT",
                        "x12": "DT_INT16",
                        "x13": "DT_INT8",
                        "x14": "DT_UINT8",
                        "x15": "DT_DOUBLE",
                        "x16": "DT_INT64",
                        "x17": "DT_INT16",
                        "x18": "DT_FLOAT",
                        "x19": "DT_FLOAT",
                        "x20": "DT_FLOAT",
                    },
                    root_node_id=0,
                    tree_nodes=[
                        {
                            "nodeId": 0,
                            "lchildId": 1,
                            "rchildId": 2,
                            "isLeaf": False,
                            "splitFeatureIdx": 9,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 1,
                            "lchildId": 3,
                            "rchildId": 4,
                            "isLeaf": False,
                            "splitFeatureIdx": 7,
                            "splitValue": -0.107344508,
                        },
                        {
                            "nodeId": 2,
                            "lchildId": 5,
                            "rchildId": 6,
                            "isLeaf": False,
                            "splitFeatureIdx": 7,
                            "splitValue": 0.210497797,
                        },
                        {
                            "nodeId": 3,
                            "lchildId": 7,
                            "rchildId": 8,
                            "isLeaf": False,
                            "splitFeatureIdx": 3,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 4,
                            "lchildId": 9,
                            "rchildId": 10,
                            "isLeaf": False,
                            "splitFeatureIdx": 3,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 5,
                            "lchildId": 11,
                            "rchildId": 12,
                            "isLeaf": False,
                            "splitFeatureIdx": 3,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 6,
                            "lchildId": 13,
                            "rchildId": 14,
                            "isLeaf": False,
                            "splitFeatureIdx": 1,
                            "splitValue": 0.510497797,
                        },
                        {
                            "nodeId": 7,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 8,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 9,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 10,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 11,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 12,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 13,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 14,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                    ],
                ),
                make_tree_select_node_def(
                    name="node_tree_select_1",
                    parents=[],
                    output_col_name="selects",
                    feature_dict={
                        "x11": "DT_FLOAT",
                        "x12": "DT_INT16",
                        "x13": "DT_INT8",
                        "x14": "DT_UINT8",
                        "x15": "DT_DOUBLE",
                        "x16": "DT_INT64",
                        "x17": "DT_INT16",
                        "x18": "DT_FLOAT",
                        "x19": "DT_FLOAT",
                        "x20": "DT_FLOAT",
                    },
                    root_node_id=0,
                    tree_nodes=[
                        {
                            "nodeId": 0,
                            "lchildId": 1,
                            "rchildId": 2,
                            "isLeaf": False,
                            "splitFeatureIdx": 9,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 1,
                            "lchildId": 3,
                            "rchildId": 4,
                            "isLeaf": False,
                            "splitFeatureIdx": 7,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 2,
                            "lchildId": 5,
                            "rchildId": 6,
                            "isLeaf": False,
                            "splitFeatureIdx": 7,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 3,
                            "lchildId": 7,
                            "rchildId": 8,
                            "isLeaf": False,
                            "splitFeatureIdx": 4,
                            "splitValue": -0.548508525,
                        },
                        {
                            "nodeId": 4,
                            "lchildId": 9,
                            "rchildId": 10,
                            "isLeaf": False,
                            "splitFeatureIdx": 3,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 5,
                            "lchildId": 11,
                            "rchildId": 12,
                            "isLeaf": False,
                            "splitFeatureIdx": 3,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 6,
                            "lchildId": 13,
                            "rchildId": 14,
                            "isLeaf": False,
                            "splitFeatureIdx": 9,
                            "splitValue": -0.405750543,
                        },
                        {
                            "nodeId": 7,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 8,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 9,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 10,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 11,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 12,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 13,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                        {
                            "nodeId": 14,
                            "lchildId": -1,
                            "rchildId": -1,
                            "isLeaf": True,
                            "splitFeatureIdx": -1,
                            "splitValue": 0,
                        },
                    ],
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_0",
                    ["node_tree_select_0"],
                    input_col_name="selects",
                    output_col_name="weights",
                ),
                make_tree_merge_node_def(
                    "node_tree_merge_1",
                    ["node_tree_select_1"],
                    input_col_name="selects",
                    output_col_name="weights",
                ),
                make_tree_ensemble_predict_node_def(
                    "node_tree_ensemble_predict",
                    ["node_tree_merge_0", "node_tree_merge_1"],
                    input_col_name="weights",
                    output_col_name="scores",
                    num_trees=2,
                    func_type='LF_SIGMOID_RAW',
                ),
            ],
        },
        executions={
            "alice": [
                ExecutionDef(
                    nodes=["node_tree_select_0", "node_tree_select_1"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=[
                        "node_tree_merge_0",
                        "node_tree_merge_1",
                        "node_tree_ensemble_predict",
                    ],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_SPECIFIED,
                        session_run=False,
                        specific_flag=True,
                    ),
                ),
            ],
            "bob": [
                ExecutionDef(
                    nodes=["node_tree_select_0", "node_tree_select_1"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=[
                        "node_tree_merge_0",
                        "node_tree_merge_1",
                        "node_tree_ensemble_predict",
                    ],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_SPECIFIED, session_run=False
                    ),
                ),
            ],
        },
        specific_party="alice",
    )


def get_glm_bob_no_feature_test():
    return MockFeatureTest(
        service_id="glm_with_bob_no_feature",
        path='model_path',
        nodes={
            "alice": [
                make_dot_product_node_def(
                    name="node_dot_product",
                    parents=[],
                    weight_dict={
                        "x21": -0.3,
                        "x22": 0.95,
                        "x23": 1.01,
                        "x24": 1.35,
                        "x25": -0.97,
                    },
                    output_col_name="y",
                    input_types=[
                        "DT_DOUBLE",
                        "DT_FLOAT",
                        "DT_INT8",
                        "DT_INT16",
                        "DT_INT32",
                    ],
                ),
                make_merge_y_node_def(
                    "node_merge_y",
                    ["node_dot_product"],
                    LinkFunctionType.LF_SIGMOID_RAW,
                    input_col_name="y",
                    output_col_name="score",
                    yhat_scale=1.2,
                ),
            ],
            "bob": [
                make_dot_product_node_def(
                    name="node_dot_product",
                    parents=[],
                    weight_dict={},
                    input_types=[],
                    intercept=1.313,
                    output_col_name="y",
                ),
                make_merge_y_node_def(
                    "node_merge_y",
                    ["node_dot_product"],
                    LinkFunctionType.LF_SIGMOID_RAW,
                    input_col_name="y",
                    output_col_name="score",
                    yhat_scale=1.2,
                ),
            ],
        },
        executions={
            "alice": [
                ExecutionDef(
                    nodes=["node_dot_product"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=["node_merge_y"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ANYONE, session_run=False
                    ),
                ),
            ],
            "bob": [
                ExecutionDef(
                    nodes=["node_dot_product"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ALL, session_run=False
                    ),
                ),
                ExecutionDef(
                    nodes=["node_merge_y"],
                    config=RuntimeConfig(
                        dispatch_type=DispatchType.DP_ANYONE, session_run=False
                    ),
                ),
            ],
        },
        feature_mappings={
            "alice": {
                "v24": "x24",
                "v22": "x22",
                "v21": "x21",
                "v25": "x25",
                "v23": "x23",
            },
            "bob": {},
        },
    )


if __name__ == "__main__":
    ExampleTest('examples').exec()

    get_mock_feature_glm_test().exec()
    get_mock_feature_sgb_test().exec()

    get_sgb_alice_no_feature_test().exec()
    get_glm_bob_no_feature_test().exec()

    PredefinedErrorTest('model_path').exec()
    PredefineTest('model_path').exec()
    CsvTest('model_path').exec()
    CsvTest('model_path', use_http_feature_source=True).exec()
    SpecificTest('model_path').exec()
