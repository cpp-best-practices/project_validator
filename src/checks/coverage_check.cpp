#include <project_validator/checks/coverage_check.hpp>

#include <algorithm>
#include <iterator>
#include <utility>

namespace project_validator {

namespace {
  [[nodiscard]] std::vector<Pattern> default_branch_patterns()
  {
    return { Pattern{ "gcovr", R"(--txt-metric[\s=]+branch)" },
      Pattern{ "gcovr", R"(--fail-under-branch)" },
      Pattern{ "gcovr", R"(--branches\b)" },
      Pattern{ "lcov", R"(\b(lcov_)?branch_coverage\s*=\s*1)" },
      Pattern{ "genhtml", R"(--branch-coverage\b)" },
      Pattern{ "gcov", R"(--branch-(probabilities|counts)\b)" },
      Pattern{ "llvm-cov", R"(-show-branch(es|-summary)\b)" } };
  }

  [[nodiscard]] std::vector<Pattern> default_path_patterns()
  {
    return { Pattern{ "gcc", R"(-fpath-coverage\b)" }, Pattern{ "gcov", R"(--prime-paths\b)" } };
  }

  [[nodiscard]] std::vector<std::string> coverage_texts(const Project &project, const std::span<const CI_File> ci_files)
  {
    auto texts = read_files(project, ci_file_paths(ci_files));
    std::ranges::move(read_files(project, project.cmake_files()), std::back_inserter(texts));
    return texts;
  }
}// namespace

Coverage_Check::Coverage_Check(CI_Providers providers)
  : Coverage_Check{ std::move(providers), default_branch_patterns(), default_path_patterns() }
{}

Coverage_Check::Coverage_Check(CI_Providers providers, std::vector<Pattern> branch_patterns, std::vector<Pattern> path_patterns)
  : m_providers{ std::move(providers) }, m_branch_patterns{ std::move(branch_patterns) },
    m_path_patterns{ std::move(path_patterns) }
{}

Check_Result Coverage_Check::run(const Project &project) const
{
  const auto texts = coverage_texts(project, find_ci_files(project, m_providers));

  const auto branch_tools = matching_names(texts, m_branch_patterns);
  if (branch_tools.empty()) { return { Status::fail, "no branch coverage reporting found in CI scripts or CMake files" }; }

  const auto path_tools = matching_names(texts, m_path_patterns);
  const auto path_summary = path_tools.empty() ? std::string{ "; consider adding path coverage (e.g. -fpath-coverage)" }
                                               : "; path coverage is checked with " + join(path_tools, ", ");

  return { Status::pass, "branch coverage is checked with " + join(branch_tools, ", ") + path_summary };
}

}// namespace project_validator
