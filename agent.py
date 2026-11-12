"""Bounded model planner. Payment/SQL/budget authority remains in Engine."""
import json
import os
from groq import Groq
from firewall import SCHEMA
from engine import Conflict
from sqlglot import parse_one,exp

def scope_fingerprint(sql):
    """Conservative optimization guard, not a proof of natural-language meaning.

    Changed outputs, filters, grouping, sources, joins or result bounds require review even when a model
    incorrectly claims scope_changed=false. Equivalent rewrites may need review.
    """
    tree=parse_one(sql,read='postgres')
    clauses = (exp.Where,exp.Having,exp.Group,exp.Table,exp.Join,exp.Order,exp.Limit,exp.Offset,exp.Distinct)
    parts = [(type(n).__name__,n.sql(dialect='postgres')) for n in tree.walk() if isinstance(n,clauses)]
    # A changed aggregate/projection can silently answer a different question
    # even when the FROM/WHERE/GROUP clauses are identical.
    parts.extend(('Projection',json.dumps([e.sql(dialect='postgres') for e in n.expressions]))
                 for n in tree.find_all(exp.Select))
    return tuple(sorted(parts))

def research(engine, sid, owner, objective):
    if os.getenv('QUERYVAULT_MODE', 'local') != 'local':
        raise Conflict('Live AI is disabled outside the local operator workflow')
    if not os.getenv("GROQ_API_KEY"):
        return {"mode":"offline", "decisions":[], "message":"No live inference configured. Use the SQL quote workbench to explore the labeled synthetic dataset.", "schema":SCHEMA}
    client = Groq(api_key=os.environ["GROQ_API_KEY"],max_retries=0,timeout=20)
    messages = [{"role":"system","content":f"You plan read-only PostgreSQL analytics. Schema: {json.dumps(SCHEMA)}. Preserve the exact objective, timeframe and granularity. Return JSON with sql, reason, and scope_changed boolean. If you cannot preserve meaning, set scope_changed true and explain; do not execute such alternatives. Never claim results before execution. At most 100 rows. Synthetic dataset dates: October 2026. No UNION, recursive CTEs, system tables or arbitrary functions."}, {"role":"user","content":objective}]
    decisions = []
    attempts = []
    initial_scope=None
    for attempt in range(3):
        model=os.getenv("GROQ_MODEL","openai/gpt-oss-20b")
        options={"reasoning_effort":"low"} if "gpt-oss" in model else {}
        reply = client.chat.completions.create(model=model, messages=messages, temperature=0, max_tokens=1800, response_format={"type":"json_object"},**options)
        raw = reply.choices[0].message.content
        messages.append({"role":"assistant","content":raw})
        try:
            proposal = json.loads(raw)
            if not isinstance(proposal,dict):
                raise ValueError('Model must return a JSON object')
            entry={'attempt':attempt+1,'sql':proposal.get('sql'),'reason':proposal.get('reason',''),'scope_changed':proposal.get('scope_changed'),'outcome':'proposed'}
            attempts.append(entry)
            empty_sql=isinstance(proposal.get('sql'),str) and not proposal['sql'].strip()
            if empty_sql and decisions and decisions[-1]['price_cents']>decisions[-1]['remaining_cents']:
                entry['outcome']='no_alternative_proposed'
                if attempt<2:
                    messages.append({'role':'user','content':'The price comes from actual PostgreSQL planning, not the number of SQL operations. Before concluding, attempt one same-scope rewrite and obtain a fresh quote. Preserve the exact filters, grouping, sources and joins. If no distinct rewrite is justified, you may submit the original full-scope SQL for an unchanged-plan requote and explicitly explain that no savings were found. Do not invent a cheaper price or claim impossibility as a proof.'})
                    continue
                return {'mode':'live_groq','decisions':decisions,'attempts':attempts,'refused':True,'message':'No affordable validated same-scope alternative was found within the attempt limit. '+str(proposal.get('reason',''))}
            if proposal.get("scope_changed") is not False:
                entry['outcome']='scope_review'
                return {"mode":"live_groq","decisions":decisions,"attempts":attempts,"requires_approval":True,"message":proposal.get("reason","Scope preservation was not confirmed; review the objective before continuing.")}
            if not isinstance(proposal.get('sql'),str):
                raise ValueError('Model must return SQL text for an unchanged scope')
            if not proposal['sql'].strip():
                entry['outcome']='model_refusal'
                return {'mode':'live_groq','decisions':decisions,'attempts':attempts,'refused':True,'message':proposal.get('reason') or 'No acceptable affordable same-scope query was proposed. No query was executed.'}
            q = engine.quote(sid,owner,proposal["sql"])
            entry.update(quote_id=q['id'],price_cents=q['price'],outcome='quoted')
            scope=scope_fingerprint(q['sql'])
            if initial_scope is None:
                initial_scope=scope
            elif scope!=initial_scope:
                entry['outcome']='scope_review'
                return {'mode':'live_groq','decisions':decisions,'attempts':attempts,'requires_approval':True,'message':'The proposal changes outputs, filters, grouping, sources, joins, ordering or result bounds. No scope-changing alternative was executed.'}
            s = engine.get(sid,owner)
            remaining = s["budget"]-s["spent"]-s["reserved"]
            entry['remaining_cents']=remaining
            decisions.append({"attempt":attempt+1,"sql":q["sql"],"price_cents":q["price"],"remaining_cents":remaining,"reason":proposal.get("reason", ""),"quote_id":q["id"]})
            if q["price"] <= remaining:
                result = engine.execute(q["id"],owner)
                entry['outcome']='executed'
                return {"mode":"live_groq","decisions":decisions,"attempts":attempts,"quote":q,"result":result}
            entry['outcome']='over_budget'
            feedback = f"Quote costs {q['price']} cents; available budget {remaining}. Try an equivalent cheaper plan. Do not narrow meaning. If impossible return sql empty."
        except (ValueError, KeyError, Conflict) as exc:
            if attempts and attempts[-1]['attempt']==attempt+1:
                attempts[-1].update(outcome='rejected',error=str(exc))
            feedback = f"Proposal rejected: {exc}. Correct the query without changing the objective."
        messages.append({"role":"user","content":feedback})
    return {"mode":"live_groq","decisions":decisions,"attempts":attempts,"refused":True,"message":"Stopped after 3 proposals; no acceptable query. No queries executed."}
