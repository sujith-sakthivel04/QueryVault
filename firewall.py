"""Fail-closed PostgreSQL analytical SQL policy. Database grants remain essential."""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope, Scope

SCHEMA = {"vault_data": {
    "shipments": {"id": "INT", "port_id": "INT", "route_id": "INT", "shipped_on": "DATE", "delay_hours": "INT", "containers": "INT"},
    "ports": {"id": "INT", "name": "TEXT", "country": "TEXT"},
    "routes": {"id": "INT", "name": "TEXT", "distance_km": "INT"},
}}
POLICY_VERSION = "logistics-v2"
SAFE_NODES = set("Select From Table Identifier Column Star Alias Literal Null Boolean Where Group Having Order Ordered Limit Offset Join With CTE Subquery Paren And Or Not EQ NEQ GT GTE LT LTE Add Sub Mul Div Mod Neg Between In Is Like ILike Distinct Case If Cast DataType DataTypeParam Interval Var Filter Count Sum Avg Min Max Round Coalesce Nullif Abs DateTrunc Extract CurrentDate".split())
SAFE_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "COALESCE", "NULLIF", "ABS", "DATE_TRUNC", "TIMESTAMP_TRUNC", "EXTRACT", "CURRENT_DATE", "CAST", "CASE", "IF"}
SAFE_NODES.update({"TableAlias","TimestampTrunc"})
SAFE_FUNCTIONS.update({"AND", "OR"})

class PolicyError(ValueError):
    pass

class QueryFirewall:
    def validate(self, sql: str) -> str:
        if not isinstance(sql, str) or not sql.strip() or len(sql) > 12000:
            raise PolicyError("SQL must contain 1–12000 characters")
        try:
            statements = sqlglot.parse(sql, read="postgres")
            if len(statements) != 1 or not isinstance(statements[0], exp.Select):
                raise PolicyError("Exactly one SELECT is supported; set operations are disabled")
            tree = statements[0]
            if len(list(tree.walk())) > 350:
                raise PolicyError("Query AST exceeds complexity limit")
            if len(list(tree.find_all(exp.Select))) > 6 or len(list(tree.find_all(exp.Join))) > 3:
                raise PolicyError("Too many subqueries or joins")
            for node in tree.walk():
                if type(node).__name__ not in SAFE_NODES:
                    raise PolicyError(f"Unsupported SQL construct: {type(node).__name__}")
                if isinstance(node, exp.Func) and node.sql_name() not in SAFE_FUNCTIONS:
                    raise PolicyError(f"Function is not allowed: {node.sql_name()}")
                if isinstance(node, exp.With) and node.args.get("recursive"):
                    raise PolicyError("Recursive CTEs are disabled")
                if isinstance(node, exp.Join) and not (node.args.get("on") or node.args.get("using")):
                    raise PolicyError("Joins require an explicit condition")
                if isinstance(node, exp.Cast) and node.args["to"].sql().upper() not in {"INT", "BIGINT", "TEXT", "DATE", "DOUBLE", "DECIMAL", "FLOAT", "BOOLEAN"}:
                    raise PolicyError("Cast type is not allowed")
            for scope in traverse_scope(tree):
                for source in scope.sources.values():
                    if isinstance(source, exp.Table):
                        if source.catalog or source.db not in ("", "vault_data") or source.name not in SCHEMA["vault_data"]:
                            raise PolicyError("Physical table/schema is not allowed")
                    elif not isinstance(source, Scope):
                        raise PolicyError("Unresolved source")
            tree = qualify(tree, dialect="postgres", db="vault_data", schema=SCHEMA,
                           validate_qualify_columns=True, allow_partial_qualification=False)
            for offset in tree.find_all(exp.Offset):
                if not isinstance(offset.expression, exp.Literal) or not offset.expression.is_int or not 0 <= int(offset.expression.this) <= 1000:
                    raise PolicyError("Offset must be a constant between 0 and 1000")
            limit = tree.args.get("limit")
            if limit:
                value = limit.expression
                if not isinstance(value, exp.Literal) or not value.is_int or int(value.this) < 0:
                    raise PolicyError("Limit must be a nonnegative integer")
                tree = tree.limit(min(100, int(value.this)))
            else:
                tree = tree.limit(100)
            return tree.sql(dialect="postgres", unsupported_level=sqlglot.ErrorLevel.RAISE)
        except PolicyError:
            raise
        except Exception as exc:
            raise PolicyError(f"SQL cannot be safely resolved: {exc}") from exc
