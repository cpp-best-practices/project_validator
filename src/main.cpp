#include <project_validator/default_checks.hpp>

#include <cstdlib>
#include <exception>
#include <filesystem>
#include <format>
#include <iostream>
#include <span>

int main(const int argc, const char *const argv[])
{
  try {
    const auto arguments = std::span{ argv, static_cast<std::size_t>(argc) };
    if (arguments.size() > 2) {
      std::cerr << std::format("usage: {} [project-directory]\n", arguments.front());
      return EXIT_FAILURE;
    }

    const auto root = arguments.size() == 2 ? std::filesystem::path{ arguments[1] } : std::filesystem::current_path();
    const auto reports = project_validator::default_registry().run_all(project_validator::Project{ root });

    for (const auto &report : reports) {
      std::cout << std::format(
        "[{}] {}: {}\n", project_validator::to_string(report.result.status), report.name, report.result.message);
    }

    return project_validator::all_passed(reports) ? EXIT_SUCCESS : EXIT_FAILURE;
  } catch (const std::exception &error) {
    std::cerr << std::format("error: {}\n", error.what());
    return EXIT_FAILURE;
  }
}
