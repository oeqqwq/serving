# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: secretflow_serving/tools/inferencer/config.proto
# Protobuf Python Version: 4.25.6
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n0secretflow_serving/tools/inferencer/config.proto\x12\x18secretflow.serving.tools\"\x8b\x01\n\x0fInferenceConfig\x12\x14\n\x0crequester_id\x18\x01 \x01(\t\x12\x18\n\x10result_file_path\x18\x02 \x01(\t\x12\x1c\n\x14\x61\x64\x64itional_col_names\x18\x03 \x03(\t\x12\x16\n\x0escore_col_name\x18\x04 \x01(\t\x12\x12\n\nblock_size\x18\x0b \x01(\x05\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'secretflow_serving.tools.inferencer.config_pb2', _globals)
if _descriptor._USE_C_DESCRIPTORS == False:
  DESCRIPTOR._options = None
  _globals['_INFERENCECONFIG']._serialized_start=79
  _globals['_INFERENCECONFIG']._serialized_end=218
# @@protoc_insertion_point(module_scope)
