#include <project_validator/checks/ctest_check.hpp>

#include <utility>

namespace project_validator {

namespace {
  [[nodiscard]] std::vector<Pattern> default_enable_patterns()
  {
    return { Pattern{ "enable_testing", R"(\benable_testing\s*\()" },
      Pattern{ "include(CTest)", R"(\binclude\s*\(\s*CTest\s*\))" } };
  }

  [[nodiscard]] std::vector<Pattern> default_test_patterns()
  {
    return { Pattern{ "add_test", R"(\badd_test\s*\()" },
      Pattern{ "catch_discover_tests", R"(\bcatch_discover_tests\s*\()" },
      Pattern{ "gtest_discover_tests", R"(\bgtest_discover_tests\s*\()" },
      Pattern{ "gtest_add_tests", R"(\bgtest_add_tests\s*\()" },
      Pattern{ "doctest_discover_tests", R"(\bdoctest_discover_tests\s*\()" } };
  }
}// namespace

CTest_Check::CTest_Check() : CTest_Check{ default_enable_patterns(), default_test_patterns() } {}

CTest_Check::CTest_Check(std::vector<Pattern> enable_patterns, std::vector<Pattern> test_patterns)
  : m_enable_patterns{ std::move(enable_patterns) }, m_test_patterns{ std::move(test_patterns) }
{}

Check_Result CTest_Check::run(const Project &project) const
{
  const auto cmake_texts = read_files(project, project.cmake_files());
  if (cmake_texts.empty()) { return { Status::fail, "no CMake files found" }; }

  if (!any_matches(cmake_texts, m_enable_patterns)) {
    return { Status::fail, "CTest is never enabled; call enable_testing() or include(CTest)" };
  }

  const auto registered = matching_names(cmake_texts, m_test_patterns);
  if (registered.empty()) { return { Status::fail, "CTest is enabled but no tests are registered" }; }

  return { Status::pass, "CTest is enabled and tests are registered with " + join(registered, ", ") };
}

}// namespace project_validator
