#include <project_validator/checks/platform_matrix_check.hpp>

#include <format>
#include <utility>

namespace project_validator {

namespace {
  [[nodiscard]] std::vector<Pattern> default_operating_systems()
  {
    return { Pattern{ "linux", R"(\b(ubuntu|linux|debian|fedora)\b)" },
      Pattern{ "windows", R"(\b(windows|win32|win64)\b|visual studio)" },
      Pattern{ "macos", R"(\b(macos|osx)\b)" } };
  }

  [[nodiscard]] std::vector<Pattern> default_compilers()
  {
    return { Pattern{ "gcc", R"(\bgcc\b|g\+\+)" },
      Pattern{ "clang", R"(\bclang(?!-tidy|-format|d)\b)" },
      Pattern{ "msvc", R"(\bmsvc\b|visual studio|\bcl\.exe\b)" },
      Pattern{ "intel", R"(\bicp?x\b|\bintel-oneapi)" } };
  }

  [[nodiscard]] std::string describe(const std::string_view kind, const std::span<const std::string> found)
  {
    return std::format("{} {} ({})", found.size(), kind, found.empty() ? std::string{ "none" } : join(found, ", "));
  }
}// namespace

Platform_Matrix_Check::Platform_Matrix_Check(const Thresholds thresholds, CI_Providers providers)
  : Platform_Matrix_Check{ thresholds, std::move(providers), default_operating_systems(), default_compilers() }
{}

Platform_Matrix_Check::Platform_Matrix_Check(const Thresholds thresholds,
  CI_Providers providers,
  std::vector<Pattern> operating_systems,
  std::vector<Pattern> compilers)
  : m_thresholds{ thresholds }, m_providers{ std::move(providers) }, m_operating_systems{ std::move(operating_systems) },
    m_compilers{ std::move(compilers) }
{}

Check_Result Platform_Matrix_Check::run(const Project &project) const
{
  const auto texts = read_files(project, ci_file_paths(find_ci_files(project, m_providers)));
  const auto operating_systems = matching_names(texts, m_operating_systems);
  const auto compilers = matching_names(texts, m_compilers);

  const auto summary = describe("operating systems", operating_systems) + " and " + describe("compilers", compilers);
  const bool enough_operating_systems = operating_systems.size() >= m_thresholds.minimum_operating_systems;
  const bool enough_compilers = compilers.size() >= m_thresholds.minimum_compilers;

  if (enough_operating_systems && enough_compilers) { return { Status::pass, "CI tests " + summary }; }

  return { Status::fail,
    std::format("CI tests {}; expected at least {} operating systems and {} compilers",
      summary,
      m_thresholds.minimum_operating_systems,
      m_thresholds.minimum_compilers) };
}

}// namespace project_validator
