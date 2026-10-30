#ifndef PROJECT_VALIDATOR_CHECK_HPP
#define PROJECT_VALIDATOR_CHECK_HPP

#include <project_validator/project.hpp>

#include <string>
#include <string_view>

namespace project_validator {

enum class Status { pass, fail };

[[nodiscard]] constexpr std::string_view to_string(const Status status) noexcept
{
  switch (status) {
  case Status::pass:
    return "PASS";
  case Status::fail:
    return "FAIL";
  }
  return "UNKNOWN";
}

struct Check_Result
{
  Status status;
  std::string message;
};

// The plugin interface: every validation rule implements Check and is added to a Registry.
class Check
{
public:
  Check() = default;
  virtual ~Check() = default;

  [[nodiscard]] virtual std::string_view name() const noexcept = 0;
  [[nodiscard]] virtual Check_Result run(const Project &project) const = 0;

protected:
  Check(const Check &) = default;
  Check(Check &&) = default;
  Check &operator=(const Check &) = default;
  Check &operator=(Check &&) = default;
};

}// namespace project_validator

#endif
