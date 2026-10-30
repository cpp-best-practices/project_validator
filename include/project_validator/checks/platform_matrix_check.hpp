#ifndef PROJECT_VALIDATOR_CHECKS_PLATFORM_MATRIX_CHECK_HPP
#define PROJECT_VALIDATOR_CHECKS_PLATFORM_MATRIX_CHECK_HPP

#include <project_validator/check.hpp>
#include <project_validator/ci_provider.hpp>
#include <project_validator/text_search.hpp>

#include <cstddef>
#include <vector>

namespace project_validator {

struct Platform_Matrix_Thresholds
{
  std::size_t minimum_operating_systems = 2;
  std::size_t minimum_compilers = 2;
};

// Passes when the CI scripts mention enough distinct operating systems and compilers.
class Platform_Matrix_Check final : public Check
{
public:
  using Thresholds = Platform_Matrix_Thresholds;

  explicit Platform_Matrix_Check(Thresholds thresholds = {}, CI_Providers providers = default_ci_providers());
  Platform_Matrix_Check(Thresholds thresholds,
    CI_Providers providers,
    std::vector<Pattern> operating_systems,
    std::vector<Pattern> compilers);

  [[nodiscard]] std::string_view name() const noexcept override { return "platform-matrix"; }
  [[nodiscard]] Check_Result run(const Project &project) const override;

private:
  Thresholds m_thresholds;
  CI_Providers m_providers;
  std::vector<Pattern> m_operating_systems;
  std::vector<Pattern> m_compilers;
};

}// namespace project_validator

#endif
