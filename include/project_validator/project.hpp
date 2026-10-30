#ifndef PROJECT_VALIDATOR_PROJECT_HPP
#define PROJECT_VALIDATOR_PROJECT_HPP

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace project_validator {

// Read-only view of the project being validated. All paths are relative to the project root.
class Project
{
public:
  explicit Project(std::filesystem::path root);

  [[nodiscard]] const std::filesystem::path &root() const noexcept { return m_root; }

  [[nodiscard]] bool exists(const std::filesystem::path &relative_path) const;
  [[nodiscard]] std::optional<std::string> read_file(const std::filesystem::path &relative_path) const;
  [[nodiscard]] std::vector<std::filesystem::path> files_in(const std::filesystem::path &relative_directory) const;
  [[nodiscard]] std::vector<std::filesystem::path> cmake_files() const;

private:
  std::filesystem::path m_root;
};

}// namespace project_validator

#endif
