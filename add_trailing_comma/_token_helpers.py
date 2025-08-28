from __future__ import annotations

from typing import NamedTuple

from tokenize_rt import ESCAPED_NL
from tokenize_rt import NON_CODING_TOKENS
from tokenize_rt import Offset
from tokenize_rt import Token
from tokenize_rt import UNIMPORTANT_WS

NEWLINES = frozenset((ESCAPED_NL, 'NEWLINE', 'NL'))
INDENT_TOKENS = frozenset(('INDENT', UNIMPORTANT_WS))
START_BRACES = frozenset(('(', '{', '['))
END_BRACES = frozenset((')', '}', ']'))


class Fix(NamedTuple):
    braces: tuple[int, int]
    multi_arg: bool
    remove_comma: bool
    initial_indent: int


def find_simple(first_brace: int, tokens: list[Token]) -> Fix | None:
    brace_stack = [first_brace]
    multi_arg = False

    for i in range(first_brace + 1, len(tokens)):
        token = tokens[i]
        if token.name == 'OP' and token.src in START_BRACES:
            brace_stack.append(i)
        elif token.name == 'OP' and token.src in END_BRACES:
            brace_stack.pop()

        if len(brace_stack) == 1 and token.src == ',':
            multi_arg = True

        if not brace_stack:
            break
    else:
        raise AssertionError('Past end?')

    last_brace = i

    # Check if we're actually multi-line
    if (
            # we were single line, but with an extra comma and or whitespace
            tokens[first_brace].line == tokens[last_brace].line and (
                tokens[last_brace - 1].name == UNIMPORTANT_WS or
                tokens[last_brace - 1].src == ','
            )
    ):
        remove_comma = True
    elif tokens[first_brace].line == tokens[last_brace].line:
        return None
    else:
        remove_comma = False

    # determine the initial indentation
    i = first_brace
    while i >= 0 and tokens[i].name not in NEWLINES:
        i -= 1

    if i >= 0 and tokens[i + 1].name in INDENT_TOKENS:
        initial_indent = len(tokens[i + 1].src)
    else:
        initial_indent = 0

    return Fix(
        (first_brace, last_brace),
        multi_arg=multi_arg,
        remove_comma=remove_comma,
        initial_indent=initial_indent,
    )


def find_call(
        arg_offsets: set[Offset],
        i: int,
        tokens: list[Token],
) -> Fix | None:
    # When we get a `call` object, the ast refers to it as this:
    #
    #     func_name(arg, arg, arg)
    #     ^ where ast points
    #
    # We care about the closing paren, in order to find it, we first walk
    # until we find an argument.  When we find an argument, we know the outer
    # paren we find is the function call paren
    #
    #     func_name(arg, arg, arg)
    #              ^ outer paren
    first_brace = None
    paren_stack = []
    for i in range(i, len(tokens)):
        token = tokens[i]
        if token.name == 'OP' and token.src == '(':
            paren_stack.append(i)
        # the ast lies to us about the beginning of parenthesized functions.
        # See #3. (why we make sure there's something to pop here)
        elif token.name == 'OP' and token.src == ')' and paren_stack:
            paren_stack.pop()

        if (token.line, token.utf8_byte_offset) in arg_offsets:
            first_brace = paren_stack[0]
            break
    else:
        raise AssertionError('Past end?')

    return find_simple(first_brace, tokens)


def fix_brace(
        tokens: list[Token],
        fix_data: Fix | None,
        add_comma: bool,
        remove_comma: bool,
) -> None:
    if fix_data is None:
        return
    first_brace, last_brace = fix_data.braces

    # From there, we can walk backwards and decide whether a comma is needed
    i = last_brace - 1
    while tokens[i].name in NON_CODING_TOKENS:
        i -= 1

    # If we're not a hugging paren, we can insert a comma
    if add_comma and tokens[i].src != ',' and i + 1 != last_brace:
        tokens.insert(i + 1, Token('OP', ','))
