// Copyright 2024 Ant Group Co., Ltd.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#pragma once

#include <mutex>

#include "arrow/csv/api.h"

#include "secretflow_serving/feature_adapter/feature_adapter.h"

namespace secretflow::serving::feature {

class StreamingAdapter : public FeatureAdapter {
 public:
  StreamingAdapter(const FeatureSourceConfig& spec,
                   const std::string& service_id, const std::string& party_id,
                   const std::shared_ptr<const arrow::Schema>& feature_schema);

  ~StreamingAdapter() override = default;

 protected:
  void OnFetchFeature(const Request& request, Response* response) override;

 private:
  std::shared_ptr<arrow::csv::StreamingReader> streaming_reader_;
  std::shared_ptr<arrow::RecordBatch> cur_batch_;
  int64_t cur_offset_;

  std::shared_ptr<arrow::RecordBatch> last_batch_;
  std::string last_context_token_;

  std::mutex mux_;
};

}  // namespace secretflow::serving::feature
