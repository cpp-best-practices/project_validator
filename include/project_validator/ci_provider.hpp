#ifndef PROJECT_VALIDATOR_CI_PROVIDER_HPP
#define PROJECT_VALIDATOR_CI_PROVIDER_HPP

#include <project_validator/project.hpp>

#include <filesystem>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace project_validator {

// Plugin interface describing how to locate the configuration files of one CI system.
class CI_Provider
{
public:
  CI_Provider() = default;
  virtual ~CI_Provider() = default;

  [[nodiscard]] virtual std::string_view name() const noexcept = 0;
  [[nodiscard]] virtual std::vector<std::filesystem::path> config_files(const Project &project) const = 0;

protected:
  CI_Provider(const CI_Provider &) = default;
  CI_Provider(CI_Provider &&) = default;
  CI_Provider &operator=(const CI_Provider &) = default;
  CI_Provider &operator=(CI_Provider &&) = default;
};

using CI_Providers = std::vector<std::unique_ptr<const CI_Provider>>;

struct Directory_Pattern
{
  std::filesystem::path directory;
  std::vector<std::string> extensions;
};

// Detects a CI system by well known file names and by files with given extensions in given directories.
class File_Pattern_CI_Provider final : public CI_Provider
{
public:
  File_Pattern_CI_Provider(std::string name,
    std::vector<std::filesystem::path> files,
    std::vector<Directory_Pattern> directories = {});

  [[nodiscard]] std::string_view name() const noexcept override { return m_name; }
  [[nodiscard]] std::vector<std::filesystem::path> config_files(const Project &project) const override;

private:
  std::string m_name;
  std::vector<std::filesystem::path> m_files;
  std::vector<Directory_Pattern> m_directories;
};

struct CI_File
{
  std::string provider;
  std::filesystem::path path;
};

[[nodiscard]] CI_Providers default_ci_providers();
[[nodiscard]] std::vector<CI_File> find_ci_files(const Project &project, std::span<const std::unique_ptr<const CI_Provider>> providers);
[[nodiscard]] std::vector<std::filesystem::path> ci_file_paths(std::span<const CI_File> files);

}// namespace project_validator

#endif
