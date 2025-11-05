from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any
import json, re

# AST node classes (same as previous cell)
@dataclass
class ASTNode:
    def to_dict(self) -> dict:
        def conv(obj):
            if isinstance(obj, ASTNode):
                return obj.to_dict()
            if isinstance(obj, list):
                return [conv(x) for x in obj]
            return obj
        return {k: conv(v) for k, v in asdict(self).items()}

@dataclass
class Program(ASTNode):
    declarations: List[ASTNode] = field(default_factory=list)
    procedures: List["Procedure"] = field(default_factory=list)

@dataclass
class Declaration(ASTNode):
    kind: str
    name: Optional[str] = None
    values: List[Any] = field(default_factory=list)

@dataclass
class Procedure(ASTNode):
    name: str
    args: List[str]
    body: "Block"

@dataclass
class Block(ASTNode):
    statements: List[ASTNode] = field(default_factory=list)

@dataclass
class Call(ASTNode):
    name: str
    args: List["Expr"] = field(default_factory=list)
    block: Optional[Block] = None

@dataclass
class Ask(ASTNode):
    agentset: "Expr"
    block: Block

@dataclass
class If(ASTNode):
    condition: "Expr"
    then_block: Block

@dataclass
class IfElse(ASTNode):
    condition: "Expr"
    then_block: Block
    else_block: Block

@dataclass
class Let(ASTNode):
    name: str
    value: "Expr"

@dataclass
class Set(ASTNode):
    name: str
    value: "Expr"

@dataclass
class Report(ASTNode):
    value: "Expr"

@dataclass
class Expr(ASTNode):
    kind: str
    value: Any = None
    left: Optional["Expr"] = None
    op: Optional[str] = None
    right: Optional["Expr"] = None
    items: Optional[List["Expr"]] = None

def sym(name:str) -> Expr: return Expr(kind="symbol", value=name)
def num(val:float|int) -> Expr: return Expr(kind="number", value=val)
def string(val:str) -> Expr: return Expr(kind="string", value=val)
def infix(left:Expr, op:str, right:Expr) -> Expr: return Expr(kind="infix", left=left, op=op, right=right)
def list_expr(items:List[Expr]) -> Expr: return Expr(kind="list", items=items)

# Tokenizer
TOKEN_SPEC = [
    ("STRING",   r'"([^"\\]|\\.)*"'),
    ("LBRACK",   r'\['),
    ("RBRACK",   r'\]'),
    ("NEWLINE",  r'\n'),
    ("NUMBER",   r'-?\d+(\.\d+)?'),
    ("OP",       r'<=|>=|!=|=|<|>|\+|\-|\*|/'),
    ("IDENT",    r"[A-Za-z_][A-Za-z0-9_\-\?\!]*"),
    ("SYMBOL",   r'[\(\),]'),
    ("SKIP",     r'[ \t\r]+'),
    ("MISMATCH", r'.')
]
MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))

def strip_comments(code:str) -> str:
    return "\n".join(line.split(';',1)[0] for line in code.splitlines())

@dataclass
class Token:
    type: str
    value: str
    pos: int

def tokenize(code:str) -> List[Token]:
    code = strip_comments(code)
    tokens = []
    for m in MASTER_RE.finditer(code):
        kind = m.lastgroup
        val = m.group()
        if kind == "SKIP":
            continue
        if kind == "MISMATCH":
            raise SyntaxError(f"Unexpected character {val!r} at pos {m.start()}")
        tokens.append(Token(kind, val, m.start()))
    return tokens

# Parser
class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.tokens[j] if 0 <= j < len(self.tokens) else None
    def match(self, *types):
        tok = self.peek()
        if tok and tok.type in types:
            self.i += 1
            return tok
        return None
    def expect(self, *types):
        tok = self.match(*types)
        if not tok:
            got = self.peek().type if self.peek() else "EOF"
            raise SyntaxError(f"Expected {types}, got {got}")
        return tok

    def parse_program(self) -> Program:
        decls, procs = [], []
        while self.peek():
            tok = self.peek()
            if tok.type == "IDENT" and tok.value in ("globals","breed","turtles-own","patches-own"):
                decls.append(self.parse_declaration())
            elif tok.type == "IDENT" and tok.value in ("to","to-report"):
                procs.append(self.parse_procedure())
            else:
                self.i += 1
        return Program(declarations=decls, procedures=procs)

    def parse_declaration(self) -> Declaration:
        kind = self.expect("IDENT").value
        values = []
        self.expect("LBRACK")
        vals = []
        while not self.match("RBRACK"):
            t = self.expect("IDENT")
            vals.append(t.value)
        values = vals
        return Declaration(kind=kind, values=values)

    def parse_procedure(self) -> Procedure:
        self.expect("IDENT")  # to / to-report
        name = self.expect("IDENT").value
        args = []
        if self.match("LBRACK"):
            while not self.match("RBRACK"):
                args.append(self.expect("IDENT").value)
        body = self.parse_block_until_end()
        return Procedure(name=name, args=args, body=body)

    def parse_block_until_end(self) -> Block:
        stmts = []
        while self.peek():
            tok = self.peek()
            if tok.type == "IDENT" and tok.value == "end":
                self.i += 1
                break
            if tok.type == "RBRACK":
                break
            if tok.type == "NEWLINE":
                self.i += 1
                continue
            stmts.append(self.parse_statement())
        return Block(statements=stmts)

    def parse_block_in_brackets(self) -> Block:
        self.expect("LBRACK")
        stmts = []
        while True:
            tok = self.peek()
            if not tok:
                raise SyntaxError("Unclosed [ block")
            if tok.type == "RBRACK":
                self.i += 1
                break
            if tok.type == "NEWLINE":
                self.i += 1
                continue
            stmts.append(self.parse_statement())
        return Block(statements=stmts)

    def parse_block_after_keyword(self) -> Block:
        while self.peek() and self.peek().type == "NEWLINE":
            self.i += 1
        return self.parse_block_in_brackets()

    def parse_statement(self) -> ASTNode:
        tok = self.expect("IDENT")
        ident = tok.value

        if ident == "if":
            cond = self.parse_expression_until_block_start()
            then_block = self.parse_block_after_keyword()
            return If(condition=cond, then_block=then_block)
        if ident == "ifelse":
            cond = self.parse_expression_until_block_start()
            then_block = self.parse_block_after_keyword()
            else_block = self.parse_block_after_keyword()
            return IfElse(condition=cond, then_block=then_block, else_block=else_block)
        if ident == "ask":
            agent = self.parse_expression_until_block_start()
            block = self.parse_block_after_keyword()
            return Ask(agentset=agent, block=block)
        if ident == "let":
            name = self.expect("IDENT").value
            value = self.parse_expression_to_eol()
            return Let(name=name, value=value)
        if ident == "set":
            name_tok = self.expect("IDENT")
            value = self.parse_expression_to_eol()
            return Set(name=name_tok.value, value=value)
        if ident == "report":
            value = self.parse_expression_to_eol()
            return Report(value=value)

        # default call
        args = self.parse_args_to_eol_or_block()
        call = Call(name=ident, args=args)
        # optional trailing block (possibly on next line)
        save_i = self.i
        while self.peek() and self.peek().type == "NEWLINE":
            self.i += 1
        if self.peek() and self.peek().type == "LBRACK":
            call.block = self.parse_block_in_brackets()
        else:
            self.i = save_i
        return call

    def parse_expression_until_block_start(self) -> Expr:
        items, depth_paren = [], 0
        while True:
            t = self.peek()
            if not t:
                break
            if t.type == "LBRACK" and depth_paren == 0:
                break
            if t.type == "NEWLINE" and depth_paren == 0:
                # Could be newline before block; stop here for condition
                break
            if t.value == "(":
                depth_paren += 1
            elif t.value == ")":
                depth_paren = max(0, depth_paren - 1)
            items.append(self.consume_expr_token())
        return self.fold_infix(items)

    def parse_expression_to_eol(self) -> Expr:
        items, depth_paren = [], 0
        while True:
            t = self.peek()
            if not t:
                break
            if t.type in ("NEWLINE","RBRACK") and depth_paren == 0:
                break
            if t.value == "(":
                depth_paren += 1
            elif t.value == ")":
                depth_paren = max(0, depth_paren - 1)
            items.append(self.consume_expr_token())
        return self.fold_infix(items)

    def parse_args_to_eol_or_block(self) -> List[Expr]:
        args = []
        while True:
            t = self.peek()
            if not t or t.type == "NEWLINE" or t.type == "RBRACK" or (t.type == "LBRACK"):
                break
            args.append(self.consume_expr_token(as_atom=True))
        return args

    def consume_expr_token(self, as_atom:bool=False) -> Expr:
        t = self.peek()
        if not t:
            raise SyntaxError("Unexpected EOF in expression")
        if t.type == "IDENT":
            self.i += 1
            return sym(t.value)
        if t.type == "NUMBER":
            self.i += 1
            return num(int(t.value)) if re.fullmatch(r"-?\d+", t.value) else num(float(t.value))
        if t.type == "STRING":
            self.i += 1
            s = t.value[1:-1].replace('\\"','"')
            return string(s)
        if t.type == "OP":
            self.i += 1
            return sym(t.value)
        if t.type == "LBRACK":
            self.i += 1
            items = []
            while True:
                if not self.peek():
                    raise SyntaxError("Unclosed list literal")
                if self.peek().type == "RBRACK":
                    self.i += 1
                    break
                if self.peek().type == "NEWLINE":
                    self.i += 1
                    continue
                items.append(self.consume_expr_token(as_atom=True))
            return list_expr(items)
        if t.type in ("SYMBOL",):
            self.i += 1
            return sym(t.value)
        raise SyntaxError(f"Unexpected token in expression: {t.type} {t.value}")

    def fold_infix(self, items: List[Expr]) -> Expr:
        if not items:
            return sym("")
        def value_of(e:Expr):
            return e.value if e.kind=="symbol" else None
        def reduce_ops(tokens, ops):
            i = 0
            out = []
            while i < len(tokens):
                e = tokens[i]
                opval = value_of(e)
                if opval in ops and out:
                    left = out.pop()
                    right = tokens[i+1] if i+1 < len(tokens) else sym("")
                    i += 2
                    out.append(infix(left, opval, right))
                else:
                    out.append(e)
                    i += 1
            return out
        tokens = reduce_ops(items, {"=","!=","<",">","<=",">="})
        tokens = reduce_ops(tokens, {"*","/"})
        tokens = reduce_ops(tokens, {"+","-"})
        tokens = reduce_ops(tokens, {"and","or"})
        if len(tokens) == 1:
            return tokens[0]
        return list_expr(tokens)

# Helpers
def ast_to_json(obj) -> str:
    return json.dumps(obj.to_dict(), indent=2)

def expr_to_text(e: Expr) -> str:
    if e is None: return ""
    if e.kind == "symbol": return str(e.value)
    if e.kind == "number": return str(e.value)
    if e.kind == "string": return f'"{e.value}"'
    if e.kind == "infix": return f"({expr_to_text(e.left)} {e.op} {expr_to_text(e.right)})"
    if e.kind == "list": return "[" + " ".join(expr_to_text(x) for x in (e.items or [])) + "]"
    return str(e)

def summarize_block(block: Block, indent=0) -> List[str]:
    lines = []
    pad = "  " * indent
    for stmt in block.statements:
        if isinstance(stmt, If):
            lines.append(f"{pad}IF {expr_to_text(stmt.condition)} THEN:")
            lines += summarize_block(stmt.then_block, indent+1)
        elif isinstance(stmt, IfElse):
            lines.append(f"{pad}IF {expr_to_text(stmt.condition)} THEN:")
            lines += summarize_block(stmt.then_block, indent+1)
            lines.append(f"{pad}ELSE:")
            lines += summarize_block(stmt.else_block, indent+1)
        elif isinstance(stmt, Ask):
            lines.append(f"{pad}ASK {expr_to_text(stmt.agentset)} DO:")
            lines += summarize_block(stmt.block, indent+1)
        elif isinstance(stmt, Set):
            lines.append(f"{pad}SET {stmt.name} = {expr_to_text(stmt.value)}")
        elif isinstance(stmt, Let):
            lines.append(f"{pad}LET {stmt.name} = {expr_to_text(stmt.value)}")
        elif isinstance(stmt, Report):
            lines.append(f"{pad}REPORT {expr_to_text(stmt.value)}")
        elif isinstance(stmt, Call):
            args = " ".join(expr_to_text(a) for a in stmt.args)
            if stmt.block:
                lines.append(f"{pad}{stmt.name.upper()} {args} THEN:")
                lines += summarize_block(stmt.block, indent+1)
            else:
                lines.append(f"{pad}{stmt.name.upper()} {args}".rstrip())
        else:
            lines.append(f"{pad}{stmt.__class__.__name__}")
    return lines

# Run on provided code
netlogo_code = r'''globals [ max-sheep ]  ; don't let the sheep population grow too large
breed [ sheep a-sheep ]
breed [ wolves wolf ]
turtles-own [ energy ]
patches-own [ countdown ]

to setup
  clear-all
  ifelse netlogo-web? [ set max-sheep 10000 ] [ set max-sheep 30000 ]

  ifelse model-version = "sheep-wolves-grass" [
    ask patches [
      set pcolor one-of [ green brown ]
      ifelse pcolor = green
        [ set countdown grass-regrowth-time ]
      [ set countdown random grass-regrowth-time ]
    ]
  ]
  [
    ask patches [ set pcolor green ]
  ]

  create-sheep initial-number-sheep
  [
    set shape  "sheep"
    set color white
    set size 1.5
    set label-color blue - 2
    set energy random (2 * sheep-gain-from-food)
    setxy random-xcor random-ycor
  ]

  create-wolves initial-number-wolves
  [
    set shape "wolf"
    set color black
    set size 2
    set energy random (2 * wolf-gain-from-food)
    setxy random-xcor random-ycor
  ]
  display-labels
  reset-ticks
end

to go
  if not any? turtles [ stop ]
  if not any? wolves and count sheep > max-sheep [ user-message "The sheep have inherited the earth" stop ]
  ask sheep [
    move
    if model-version = "sheep-wolves-grass" [
      set energy energy - 1
      eat-grass
      death
    ]
    reproduce-sheep
  ]
  ask wolves [
    move
    set energy energy - 1
    eat-sheep
    death
    reproduce-wolves
  ]
  if model-version = "sheep-wolves-grass" [ ask patches [ grow-grass ] ]
  tick
  display-labels
end

to move
  rt random 50
  lt random 50
  fd 1
end

to eat-grass
  if pcolor = green [
    set pcolor brown
    set energy energy + sheep-gain-from-food
  ]
end

to reproduce-sheep
  if random-float 100 < sheep-reproduce [
    set energy (energy / 2)
    hatch 1 [ rt random-float 360 fd 1 ]
  ]
end

to reproduce-wolves
  if random-float 100 < wolf-reproduce [
    set energy (energy / 2)
    hatch 1 [ rt random-float 360 fd 1 ]
  ]
end

to eat-sheep
  let prey one-of sheep-here
  if prey != nobody  [
    ask prey [ die ]
    set energy energy + wolf-gain-from-food
  ]
end

to death
  if energy < 0 [ die ]
end

to grow-grass
  if pcolor = brown [
    ifelse countdown <= 0
      [ set pcolor green
        set countdown grass-regrowth-time ]
      [ set countdown countdown - 1 ]
  ]
end

to-report grass
  ifelse model-version = "sheep-wolves-grass" [
    report patches with [pcolor = green]
  ]
  [ report 0 ]
end

to display-labels
  ask turtles [ set label "" ]
  if show-energy? [
    ask wolves [ set label round energy ]
    if model-version = "sheep-wolves-grass" [ ask sheep [ set label round energy ] ]
  ]
end
'''

tokens = tokenize(netlogo_code)
parser = Parser(tokens)
program = parser.parse_program()
go_proc = {p.name: p for p in program.procedures}.get("move")

def ast_to_json(obj) -> str:
    return json.dumps(obj.to_dict(), indent=2)

def expr_to_text(e: Expr) -> str:
    if e is None: return ""
    if e.kind == "symbol": return str(e.value)
    if e.kind == "number": return str(e.value)
    if e.kind == "string": return f'"{e.value}"'
    if e.kind == "infix": return f"({expr_to_text(e.left)} {e.op} {expr_to_text(e.right)})"
    if e.kind == "list": return "[" + " ".join(expr_to_text(x) for x in (e.items or [])) + "]"
    return str(e)

def summarize_block(block: Block, indent=0) -> List[str]:
    lines = []
    pad = "  " * indent
    for stmt in block.statements:
        if isinstance(stmt, If):
            lines.append(f"{pad}IF {expr_to_text(stmt.condition)} THEN:")
            lines += summarize_block(stmt.then_block, indent+1)
        elif isinstance(stmt, IfElse):
            lines.append(f"{pad}IF {expr_to_text(stmt.condition)} THEN:")
            lines += summarize_block(stmt.then_block, indent+1)
            lines.append(f"{pad}ELSE:")
            lines += summarize_block(stmt.else_block, indent+1)
        elif isinstance(stmt, Ask):
            lines.append(f"{pad}ASK {expr_to_text(stmt.agentset)} DO:")
            lines += summarize_block(stmt.block, indent+1)
        elif isinstance(stmt, Set):
            lines.append(f"{pad}SET {stmt.name} = {expr_to_text(stmt.value)}")
        elif isinstance(stmt, Let):
            lines.append(f"{pad}LET {stmt.name} = {expr_to_text(stmt.value)}")
        elif isinstance(stmt, Report):
            lines.append(f"{pad}REPORT {expr_to_text(stmt.value)}")
        elif isinstance(stmt, Call):
            args = " ".join(expr_to_text(a) for a in stmt.args)
            if stmt.block:
                lines.append(f"{pad}{stmt.name.upper()} {args} THEN:")
                lines += summarize_block(stmt.block, indent+1)
            else:
                lines.append(f"{pad}{stmt.name.upper()} {args}".rstrip())
        else:
            lines.append(f"{pad}{stmt.__class__.__name__}")
    return lines

focused_json = ast_to_json(go_proc) if go_proc else "{}"
summary_text = "\n".join(summarize_block(go_proc.body) if go_proc else ["<go not found>"])

with open("netlogo_ast.json","w", encoding="utf-8") as f:
    f.write(json.dumps(program.to_dict(), indent=2))
with open("go_ast.json","w", encoding="utf-8") as f:
    f.write(focused_json)
with open("go_summary.txt","w", encoding="utf-8") as f:
    f.write(summary_text)

print("=== Procedure 'go' AST ===")
print(focused_json[:100000])
print("\n=== Who does what when (summary) ===")
print(summary_text)
print("\nArtifacts:")
print("- Full AST: netlogo_ast.json")
print("- 'go' AST: go_ast.json")
print("- Summary:  go_summary.txt")
