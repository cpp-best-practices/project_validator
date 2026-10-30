#include <project_validator/project.hpp>

#include <algorithm>
#include <fstream>
#include <iterator>
#include <sstream>
#include <system_error>
#include <utility>

namespace project_validator {

namespace {
  [[nodiscard]] bool is_hidden(const std::filesystem::path &path)
  {
    const auto name = path.filename().string();
    return name.size() > 1 && name.front() == '.';
  }

  [[nodiscard]] bool is_build_tree(const std::filesystem::path &directory)
  {
    std::error_code error;
    return std::filesystem::exists(directory / "CMakeCache.txt", error);
  }

  [[nodiscard]] bool is_cmake_file(const std::filesystem::path &path)
  {
    return path.filename() == "CMakeLists.txt" || path.extension() == ".cmake";
  }
}// namespace

Project::Project(std::filesystem::path root) : m_root{ std::move(root) } {}

bool Project::exists(const std::filesystem::path &relative_path) const
{
  std::error_code error;
  return std::filesystem::exists(m_root / relative_path, error);
}

std::optional<std::string> Project::read_file(const std::filesystem::path &relative_path) const
{
  const auto full_path = m_root / relative_path;
  std::error_code error;
  if (!std::filesystem::is_regular_file(full_path, error)) { return std::nullopt; }

  std::ifstream file{ full_path, std::ios::binary };
  if (!file) { return std::nullopt; }

  std::ostringstream contents;
  contents << file.rdbuf();
  return std::move(contents).str();
}

std::vector<std::filesystem::path> Project::files_in(const std::filesystem::path &relative_directory) const
{
  std::vector<std::filesystem::path> files;
  std::error_code error;
  for (const auto &entry : std::filesystem::directory_iterator{ m_root / relative_directory, error }) {
    if (entry.is_regular_file(error)) { files.push_back(relative_directory / entry.path().filename()); }
  }
  std::ranges::sort(files);
  return files;
}

std::vector<std::filesystem::path> Project::cmake_files() const
{
  std::vector<std::filesystem::path> files;
  std::error_code error;
  auto iterator = std::filesystem::recursive_directory_iterator{ m_root, error };
  for (const auto end = std::filesystem::recursive_directory_iterator{}; iterator != end; iterator.increment(error)) {
    const auto &entry = *iterator;
    if (entry.is_directory(error)) {
      if (is_hidden(entry.path()) || is_build_tree(entry.path())) { iterator.disable_recursion_pending(); }
    } else if (entry.is_regular_file(error) && is_cmake_file(entry.path())) {
      files.push_back(std::filesystem::relative(entry.path(), m_root, error));
    }
  }
  std::ranges::sort(files);
  return files;
}

}// namespace project_validator
