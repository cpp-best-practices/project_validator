#ifndef PROJECT_VALIDATOR_CHECKS_COVERAGE_CHECK_HPP
#define PROJECT_VALIDATOR_CHECKS_COVERAGE_CHECK_HPP

#include <project_validator/check.hpp>
#include <project_validator/ci_provider.hpp>
#include <project_validator/text_search.hpp>

#include <vector>

namespace project_validator {

// Passes when CI scripts or CMake files measure branch coverage; also reports whether path coverage is measured.
class Coverage_Check final : public Check
{
public:
  explicit Coverage_Check(CI_Providers providers = default_ci_providers());
  Coverage_Check(CI_Providers providers, std::vector<Pattern> branch_patterns, std::vector<Pattern> path_patterns);

  [[nodiscard]] std::string_view name() const noexcept override { return "coverage"; }
  [[nodiscard]] Check_Result run(const Project &project) const override;

private:
  CI_Providers m_providers;
  std::vector<Pattern> m_branch_patterns;
  std::vector<Pattern> m_path_patterns;
};

}// namespace project_validator

#endif
