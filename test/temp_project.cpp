#include "temp_project.hpp"

#include <format>
#include <fstream>
#include <random>
#include <stdexcept>
#include <system_error>

namespace project_validator::test {

namespace {
  [[nodiscard]] std::filesystem::path unique_directory_name()
  {
    std::random_device device;
    std::mt19937_64 engine{ device() };
    return std::format("project_validator_test_{:016x}", engine());
  }
}// namespace

Temp_Project::Temp_Project() : m_root{ std::filesystem::temp_directory_path() / unique_directory_name() }
{
  std::filesystem::create_directories(m_root);
}

Temp_Project::~Temp_Project()
{
  std::error_code error;
  std::filesystem::remove_all(m_root, error);
}

Temp_Project &Temp_Project::write(const std::filesystem::path &relative_path, const std::string_view content)
{
  const auto full_path = m_root / relative_path;
  std::filesystem::create_directories(full_path.parent_path());
  std::ofstream file{ full_path, std::ios::binary };
  if (!file) { throw std::runtime_error(std::format("unable to create '{}'", full_path.string())); }
  file.write(content.data(), static_cast<std::streamsize>(content.size()));
  return *this;
}

Temp_Project &Temp_Project::make_directory(const std::filesystem::path &relative_path)
{
  std::filesystem::create_directories(m_root / relative_path);
  return *this;
}

}// namespace project_validator::test
