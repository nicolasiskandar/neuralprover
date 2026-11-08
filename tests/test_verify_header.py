"""Declaration headers the verifier must parse before it can check axioms.

`LeanClient.verify` appends `#print axioms <name>`.  If the name is not found,
the verifier must refuse to verify rather than silently skip that check.
"""
import pytest

from neuralproof.lean.client import _axioms, _declaration_name


@pytest.mark.parametrize("header, expected", [
    ("theorem foo : True := by trivial", "foo"),
    ("lemma bar : True := by trivial", "bar"),
    ("private theorem foo : False := bad", "foo"),
    ("protected theorem foo : False := bad", "foo"),
    ("@[simp] theorem foo : False := bad", "foo"),
    ("@[simp]\nprivate theorem foo : False := bad", "foo"),
    ("@[simp, norm_cast]\ntheorem foo : False := bad", "foo"),
    ("/-- doc -/ theorem foo : True := by trivial", "foo"),
    ("/- comment -/\ntheorem foo : True := by trivial", "foo"),
    ("-- comment\ntheorem foo : True := by trivial", "foo"),
    ("theorem foo.{u} : True := by trivial", "foo"),
    ("theorem «odd name» : True := by trivial", "«odd name»"),
    ("axiom fabricated : True\ntheorem unsound : True := fabricated", "unsound"),
    ("open Foo in\ntheorem foo : True := by trivial", "foo"),
])
def test_a_declaration_header_yields_the_name_axioms_needs(header, expected):
    assert _declaration_name(header) == expected


@pytest.mark.parametrize("header", [
    "example : False := bad",
    "def foo : Nat := 1",
    "axiom foo : False",
])
def test_an_unknown_header_is_not_silently_accepted(header):
    assert _declaration_name(header) is None


def test_the_axiom_parser_reports_when_the_command_did_not_run():
    assert _axioms(()) == ((), False)


def test_the_axiom_parser_reports_a_constructive_proof():
    messages = ({"severity": "information",
                 "data": "'foo' does not depend on any axioms"},)
    assert _axioms(messages) == ((), True)


def test_the_axiom_parser_reports_the_dependencies():
    messages = ({"severity": "information",
                 "data": "'foo' depends on axioms: [propext, bad]"},)
    assert _axioms(messages) == (("propext", "bad"), True)
