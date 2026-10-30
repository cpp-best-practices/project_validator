#include <project_validator/checks/has_ci_check.hpp>
#include <project_validator/text_search.hpp>

#include <algorithm>
#include <iterator>
#include <utility>

namespace project_validator {

namespace {
  [[nodiscard]] std::vector<std::string> unique_provider_names(const std::span<const CI_File> files)
  {
    std::vector<std::string> names;
    for (const auto &file : files) {
      if (std::ranges::find(names, file.provider) == names.end()) { names.push_back(file.provider); }
    }
    return names;
  }

  [[nodiscard]] std::vector<std::string> provider_names(const std::span<const std::unique_ptr<const CI_Provider>> providers)
  {
    std::vector<std::string> names;
    std::ranges::transform(
      providers, std::back_inserter(names), [](const auto &provider) { return std::string{ provider->name() }; });
    return names;
  }
}// namespace

Has_CI_Check::Has_CI_Check(CI_Providers providers) : m_providers{ std::move(providers) } {}

Check_Result Has_CI_Check::run(const Project &project) const
{
  const auto files = find_ci_files(project, m_providers);
  if (files.empty()) {
    return { Status::fail, "no CI configuration found (looked for " + join(provider_names(m_providers), ", ") + ")" };
  }
  return { Status::pass, "CI configuration found for " + join(unique_provider_names(files), ", ") };
}

}// namespace project_validator
