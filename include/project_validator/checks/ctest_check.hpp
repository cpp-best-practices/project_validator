#ifndef PROJECT_VALIDATOR_CHECKS_CTEST_CHECK_HPP
#define PROJECT_VALIDATOR_CHECKS_CTEST_CHECK_HPP

#include <project_validator/check.hpp>
#include <project_validator/text_search.hpp>

#include <vector>

namespace project_validator {

// Passes when the CMake files enable CTest and register at least one test with it.
class CTest_Check final : public Check
{
public:
  CTest_Check();
  CTest_Check(std::vector<Pattern> enable_patterns, std::vector<Pattern> test_patterns);

  [[nodiscard]] std::string_view name() const noexcept override { return "ctest"; }
  [[nodiscard]] Check_Result run(const Project &project) const override;

private:
  std::vector<Pattern> m_enable_patterns;
  std::vector<Pattern> m_test_patterns;
};

}// namespace project_validator

#endif
