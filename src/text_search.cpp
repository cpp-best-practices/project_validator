#include <project_validator/text_search.hpp>

#include <algorithm>
#include <utility>

namespace project_validator {

Pattern::Pattern(std::string pattern_name, const std::string_view expression)
  : name{ std::move(pattern_name) }, regex{ expression.begin(), expression.end(), std::regex::ECMAScript | std::regex::icase }
{}

bool matches(const std::string_view text, const Pattern &pattern)
{
  return std::regex_search(text.begin(), text.end(), pattern.regex);
}

bool any_matches(const std::span<const std::string> texts, const Pattern &pattern)
{
  return std::ranges::any_of(texts, [&pattern](const auto &text) { return matches(text, pattern); });
}

bool any_matches(const std::span<const std::string> texts, const std::span<const Pattern> patterns)
{
  return std::ranges::any_of(patterns, [texts](const auto &pattern) { return any_matches(texts, pattern); });
}

std::vector<std::string> matching_names(const std::span<const std::string> texts, const std::span<const Pattern> patterns)
{
  std::vector<std::string> names;
  for (const auto &pattern : patterns) {
    if (any_matches(texts, pattern) && std::ranges::find(names, pattern.name) == names.end()) {
      names.push_back(pattern.name);
    }
  }
  return names;
}

std::vector<std::string> read_files(const Project &project, const std::span<const std::filesystem::path> files)
{
  std::vector<std::string> contents;
  contents.reserve(files.size());
  for (const auto &file : files) {
    if (auto text = project.read_file(file)) { contents.push_back(std::move(*text)); }
  }
  return contents;
}

std::string join(const std::span<const std::string> values, const std::string_view separator)
{
  std::string result;
  for (const auto &value : values) {
    if (!result.empty()) { result += separator; }
    result += value;
  }
  return result;
}

}// namespace project_validator
