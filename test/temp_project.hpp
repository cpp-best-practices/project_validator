#ifndef PROJECT_VALIDATOR_TEST_TEMP_PROJECT_HPP
#define PROJECT_VALIDATOR_TEST_TEMP_PROJECT_HPP

#include <project_validator/project.hpp>

#include <filesystem>
#include <string_view>

namespace project_validator::test {

// Owns a uniquely named directory on disk for the lifetime of the object.
class Temp_Project
{
public:
  Temp_Project();
  ~Temp_Project();

  Temp_Project(const Temp_Project &) = delete;
  Temp_Project &operator=(const Temp_Project &) = delete;
  Temp_Project(Temp_Project &&) = delete;
  Temp_Project &operator=(Temp_Project &&) = delete;

  Temp_Project &write(const std::filesystem::path &relative_path, std::string_view content);
  Temp_Project &make_directory(const std::filesystem::path &relative_path);

  [[nodiscard]] const std::filesystem::path &root() const noexcept { return m_root; }
  [[nodiscard]] Project project() const { return Project{ m_root }; }

private:
  std::filesystem::path m_root;
};

}// namespace project_validator::test

#endif
