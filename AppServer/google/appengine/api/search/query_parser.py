#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#




"""Wrapper for QueryParser."""


from google.appengine._internal import antlr3
from google.appengine._internal.antlr3 import tree
from google.appengine.api.search import QueryLexer
from google.appengine.api.search import QueryParser


COMPARISON_TYPES = [
    QueryParser.EQ,
    QueryParser.NE,
    QueryParser.GT,
    QueryParser.GE,
    QueryParser.LT,
    QueryParser.LE,
    ]


class QueryException(Exception):
  """An error occurred while parsing the query input string."""


class QueryTreeException(Exception):
  """An error occurred while analyzing the parse tree."""

  def __init__(self, msg, position):
    Exception.__init__(self, msg)
    self.position = position


class QueryLexerWithErrors(QueryLexer.QueryLexer):
  """An overridden Lexer that raises exceptions."""

  def displayRecognitionError(self, tokenNames, e):
    msg = "WARNING: query error at line %d:%d" % (e.line, e.charPositionInLine);
    self.emitErrorMessage(msg)

  def emitErrorMessage(self, msg):
    """Raise an exception if the input fails to parse correctly.

    Overriding the default, which normally just prints a message to
    stderr.

    Arguments:
      msg: the error message
    Raises:
      QueryException: always.
    """
    raise QueryException(msg)


class QueryParserWithErrors(QueryParser.QueryParser):
  """An overridden Parser that raises exceptions."""

  def displayRecognitionError(self, tokenNames, e):
    msg = "WARNING: query error at line %d:%d" % (e.line, e.charPositionInLine);
    self.emitErrorMessage(msg)

  def emitErrorMessage(self, msg):
    """Raise an exception if the input fails to parse correctly.

    Overriding the default, which normally just prints a message to
    stderr.

    Arguments:
      msg: the error message
    Raises:
      QueryException: always.
    """
    raise QueryException(msg)


def CreateParser(query):
  """Creates a Query Parser."""
  input_string = antlr3.ANTLRStringStream(query)
  lexer = QueryLexerWithErrors(input_string)
  tokens = antlr3.CommonTokenStream(lexer)
  parser = QueryParserWithErrors(tokens)
  return parser


def ParseAndSimplify(query):
  """Parses a query and performs all necessary transformations on the tree."""
  node = Parse(query).tree
  node = _ColonToEquals(node)
  node = SequenceToConjunction(node)
  try:
    node = SimplifyNode(node)
  except QueryTreeException, e:
    msg = "%s in query '%s'" % (e.message, query)
    raise QueryException(msg)
  return node


def Parse(query):
  """Parses a query and returns an ANTLR tree."""
  parser = CreateParser(query)
  try:
    return parser.query()
  except Exception, e:
    msg = "%s in query '%s'" % (e.message, query)
    raise QueryException(msg)


def ConvertNodes(node, from_type, to_type, to_text):
  """Converts nodes of type from_type to nodes of type to_type."""
  if node.getType() == from_type:
    new_node = CreateQueryNode(to_text, to_type)
  else:
    new_node = node
  convert_children = lambda c: ConvertNodes(c, from_type, to_type, to_text)
  new_node.children = map(convert_children, node.children)
  return new_node


def _ColonToEquals(node):
  """Transform all HAS nodes into EQ nodes.

  Equals and colon have the same semantic meaning in the query language, so to
  simplify matching code we translate all HAS nodes into EQ nodes.

  Arguments:
    node: Root of the tree to transform.

  Returns:
    A tree with all HAS nodes replaced with EQ nodes.
  """
  return ConvertNodes(node, QueryParser.HAS, QueryParser.EQ, '=')


def SequenceToConjunction(node):
  """Transform all SEQUENCE nodes into CONJUNCTION nodes.

  Sequences have the same semantic meaning as conjunctions, so we transform them
  to conjunctions to make query matching code simpler.

  Arguments:
    node: Root of the tree to transform.

  Returns:
    A tree with all SEQUENCE nodes replaced with CONJUNCTION nodes.
  """
  return ConvertNodes(
      node, QueryParser.SEQUENCE, QueryParser.CONJUNCTION, 'CONJUNCTION')


def Simplify(parser_return):
  """Simplifies the output of the parser."""
  if parser_return.tree:
    return SimplifyNode(parser_return.tree)
  return parser_return


def SimplifyNode(tree, restriction=None):
  if tree.getType() == QueryLexer.VALUE:
    return tree
  elif tree.getType() == QueryParser.CONJUNCTION and tree.getChildCount() == 1:
    return SimplifyNode(tree.children[0], restriction)
  elif tree.getType() == QueryParser.DISJUNCTION and tree.getChildCount() == 1:
    return SimplifyNode(tree.children[0], restriction)
  elif tree.getType() == QueryLexer.HAS or tree.getType() == QueryLexer.EQ:
    lhs = tree.getChild(0);
    if lhs.getType() == QueryLexer.VALUE:
      myField = lhs.getChild(1).getText()
      if restriction is None:
        restriction = lhs
      else:
        otherField = restriction.getChild(1).getText();
        if myField != otherField:
          raise QueryTreeException(
              "Restriction on %s and %s" % (otherField, myField),
              lhs.getChild(1).getCharPositionInLine());
    rhs = tree.getChild(1);
    flattened = SimplifyNode(rhs, restriction);
    if (flattened.getType() == QueryLexer.HAS or
        flattened.getType() == QueryLexer.EQ or
        flattened.getType() == QueryLexer.CONJUNCTION or
        flattened.getType() == QueryLexer.DISJUNCTION or
        flattened.getType() == QueryLexer.SEQUENCE):
      return flattened;
    if flattened != rhs:
      tree.setChild(1, flattened);
    if restriction != lhs:
      tree.setChild(0, restriction);
    return tree;
  for i in range(tree.getChildCount()):
    original = tree.getChild(i);
    flattened = SimplifyNode(tree.getChild(i), restriction);
    if original != flattened:
      tree.setChild(i, flattened)
  return tree;

def CreateQueryNode(text, type):
  token = tree.CommonTreeAdaptor().createToken(tokenType=type, text=text)
  return tree.CommonTree(token)


def GetQueryNodeText(node):
  """Returns the text from the node, handling that it could be unicode."""
  return GetQueryNodeTextUnicode(node).encode('utf-8')


def GetQueryNodeTextUnicode(node):
  """Returns the unicode text from node."""
  if node.getType() == QueryParser.VALUE and len(node.children) >= 2:
    return u''.join(c.getText() for c in node.children[1:])
  elif node.getType() == QueryParser.VALUE:
    return None
  return node.getText()


def GetPhraseQueryNodeText(node):
  """Returns the text from a query node."""
  text = GetQueryNodeText(node)
  if text:



    if text[0] == '"' and text[-1] == '"':
      text = text[1:-1]
  return text


def IsPhrase(node):
  """Return true if node is the root of a text phrase."""
  text = GetQueryNodeText(node)
  return (node.getType() == QueryParser.VALUE and
          text.startswith('"') and text.endswith('"'))
