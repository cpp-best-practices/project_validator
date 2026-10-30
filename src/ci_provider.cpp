#include <project_validator/ci_provider.hpp>

#include <algorithm>
#include <iterator>
#include <utility>

namespace project_validator {

namespace {
  [[nodiscard]] bool has_extension(const std::filesystem::path &path, const std::span<const std::string> extensions)
  {
    return std::ranges::find(extensions, path.extension().string()) != extensions.end();
  }

  [[nodiscard]] std::unique_ptr<const CI_Provider> make_provider(std::string name,
    std::vector<std::filesystem::path> files,
    std::vector<Directory_Pattern> directories = {})
  {
    return std::make_unique<const File_Pattern_CI_Provider>(std::move(name), std::move(files), std::move(directories));
  }
}// namespace

File_Pattern_CI_Provider::File_Pattern_CI_Provider(std::string name,
  std::vector<std::filesystem::path> files,
  std::vector<Directory_Pattern> directories)
  : m_name{ std::move(name) }, m_files{ std::move(files) }, m_directories{ std::move(directories) }
{}

std::vector<std::filesystem::path> File_Pattern_CI_Provider::config_files(const Project &project) const
{
  std::vector<std::filesystem::path> found;
  std::ranges::copy_if(m_files, std::back_inserter(found), [&project](const auto &file) { return project.exists(file); });

  for (const auto &[directory, extensions] : m_directories) {
    std::ranges::copy_if(project.files_in(directory), std::back_inserter(found), [&extensions](const auto &file) {
      return has_extension(file, extensions);
    });
  }
  return found;
}

CI_Providers default_ci_providers()
{
  CI_Providers providers;
  providers.push_back(
    make_provider("GitHub Actions", {}, { Directory_Pattern{ ".github/workflows", { ".yml", ".yaml" } } }));
  providers.push_back(make_provider("GitLab CI", { ".gitlab-ci.yml" }));
  providers.push_back(make_provider("Azure Pipelines", { "azure-pipelines.yml", ".azure-pipelines.yml" }));
  providers.push_back(make_provider("AppVeyor", { "appveyor.yml", ".appveyor.yml" }));
  providers.push_back(make_provider("CircleCI", { ".circleci/config.yml" }));
  providers.push_back(make_provider("Travis CI", { ".travis.yml" }));
  providers.push_back(make_provider("Jenkins", { "Jenkinsfile" }));
  providers.push_back(make_provider("Drone", { ".drone.yml" }));
  return providers;
}

std::vector<CI_File> find_ci_files(const Project &project, const std::span<const std::unique_ptr<const CI_Provider>> providers)
{
  std::vector<CI_File> found;
  for (const auto &provider : providers) {
    std::ranges::transform(provider->config_files(project), std::back_inserter(found), [&provider](auto path) {
      return CI_File{ std::string{ provider->name() }, std::move(path) };
    });
  }
  return found;
}

std::vector<std::filesystem::path> ci_file_paths(const std::span<const CI_File> files)
{
  std::vector<std::filesystem::path> paths;
  paths.reserve(files.size());
  std::ranges::transform(files, std::back_inserter(paths), &CI_File::path);
  return paths;
}

}// namespace project_validator
