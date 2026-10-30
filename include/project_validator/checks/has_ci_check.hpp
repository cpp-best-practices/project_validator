#ifndef PROJECT_VALIDATOR_CHECKS_HAS_CI_CHECK_HPP
#define PROJECT_VALIDATOR_CHECKS_HAS_CI_CHECK_HPP

#include <project_validator/check.hpp>
#include <project_validator/ci_provider.hpp>

namespace project_validator {

// Passes when at least one of the configured CI providers finds configuration files.
class Has_CI_Check final : public Check
{
public:
  explicit Has_CI_Check(CI_Providers providers = default_ci_providers());

  [[nodiscard]] std::string_view name() const noexcept override { return "has-ci"; }
  [[nodiscard]] Check_Result run(const Project &project) const override;

private:
  CI_Providers m_providers;
};

}// namespace project_validator

#endif
