#ifndef PROJECT_VALIDATOR_REGISTRY_HPP
#define PROJECT_VALIDATOR_REGISTRY_HPP

#include <project_validator/check.hpp>

#include <cstddef>
#include <memory>
#include <span>
#include <string>
#include <utility>
#include <vector>

namespace project_validator {

struct Check_Report
{
  std::string name;
  Check_Result result;
};

class Registry
{
public:
  void add(std::unique_ptr<const Check> check);

  template<typename Check_Type, typename... Args> const Check_Type &emplace(Args &&...args)
  {
    auto check = std::make_unique<const Check_Type>(std::forward<Args>(args)...);
    const auto &result = *check;
    add(std::move(check));
    return result;
  }

  [[nodiscard]] std::size_t size() const noexcept { return m_checks.size(); }
  [[nodiscard]] std::vector<Check_Report> run_all(const Project &project) const;

private:
  std::vector<std::unique_ptr<const Check>> m_checks;
};

[[nodiscard]] bool all_passed(std::span<const Check_Report> reports);

}// namespace project_validator

#endif
