#include <project_validator/registry.hpp>

#include <algorithm>
#include <iterator>
#include <stdexcept>

namespace project_validator {

void Registry::add(std::unique_ptr<const Check> check)
{
  if (check == nullptr) { throw std::invalid_argument("Registry::add requires a non-null check"); }
  m_checks.push_back(std::move(check));
}

std::vector<Check_Report> Registry::run_all(const Project &project) const
{
  std::vector<Check_Report> reports;
  reports.reserve(m_checks.size());
  std::ranges::transform(m_checks, std::back_inserter(reports), [&project](const auto &check) {
    return Check_Report{ std::string{ check->name() }, check->run(project) };
  });
  return reports;
}

bool all_passed(const std::span<const Check_Report> reports)
{
  return std::ranges::all_of(reports, [](const auto &report) { return report.result.status == Status::pass; });
}

}// namespace project_validator
