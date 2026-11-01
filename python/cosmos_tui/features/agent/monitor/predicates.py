"""Bounded text predicates for terminal watches."""

import regex

TEXT_CONDITIONS = ("text_present", "text_absent", "regex_present", "regex_absent")


def validate_pattern(condition, text):
    if condition.startswith("regex_"):
        try:
            regex.compile(text)
        except regex.error as error:
            raise ValueError(f"Invalid watch regex: {error}") from error


def text_matches(condition, pattern, text):
    if condition.startswith("regex_"):
        try:
            present = regex.search(pattern, text, timeout=0.02) is not None
        except regex.error as error:
            raise ValueError(f"Invalid watch regex: {error}") from error
    else:
        present = pattern in text
    return present if condition.endswith("_present") else not present
