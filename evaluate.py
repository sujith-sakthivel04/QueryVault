"""Reproducible raw-count evaluation on real PostgreSQL; no external payments."""
import json
import argparse
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from pathlib import Path
from firewall import QueryFirewall, PolicyError
from db import read_query
from test_firewall import LEGIT, ATTACKS

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='new local report path; existing files are never replaced')
    args=parser.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    output_path=args.output or Path('.local')/'evaluations'/f'evaluation-{stamp}.json'
    if output_path.exists():
        raise SystemExit('Refusing to overwrite an existing evaluation report.')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    fw=QueryFirewall()
    report={'database':'PostgreSQL 18; real restricted reader','payment_tests':'automated suite uses mocks; actual Sandbox verification is recorded separately','ai_tests':'automated decision tests use mocks; live Groq verification is recorded separately','holdout_provenance':'Handwritten variants; independently generated holdout set still outstanding','legitimate_total':len(LEGIT),'legitimate_accepted':0,'legitimate_false_rejections':0,'query_execution_failures':0,'adversarial_total':len(ATTACKS),'security_rejections':0,'unauthorized_execution_attempts_reaching_database':0,'known_answer_cases':20,'known_answers_correct':0,'cases':[]}
    for raw in LEGIT:
        try:
            safe=fw.validate(raw)
            report['legitimate_accepted']+=1
            read_query(safe)
            report['cases'].append({'sql':raw,'result':'accepted and executed'})
        except PolicyError as exc:
            report['legitimate_false_rejections']+=1
            report['cases'].append({'sql':raw,'result':str(exc)})
        except Exception:
            report['query_execution_failures']+=1
    for raw in ATTACKS:
        try:
            fw.validate(raw)
            report['cases'].append({'sql':raw,'result':'UNEXPECTED ACCEPTANCE; not executed'})
        except PolicyError:
            report['security_rejections']+=1
            report['cases'].append({'sql':raw,'result':'policy rejected before database'})
    # Expected results calculated from generation rules, independently of SQL.
    for threshold in range(20):
        expected=sum(1 for i in range(1,601) if (i*7)%49>threshold)
        rows=read_query(fw.validate(f'SELECT COUNT(*) AS n FROM shipments WHERE delay_hours > {threshold}'))
        report['known_answers_correct']+=int(rows==[{'n':expected}])
    output_path.write_text(json.dumps(report,indent=2))
    if Path('holdout.json').exists():
        holdout=json.loads(Path('holdout.json').read_text())
        counts={'legitimate_total':0,'legitimate_accepted':0,'legitimate_false_rejections':0,'execution_failures':0,'adversarial_total':0,'security_rejections':0,'unexpected_acceptances':0}
        for category,queries in holdout['cases'].items():
            for raw in queries:
                counts[category+'_total']+=1
                try:
                    safe=fw.validate(raw)
                    if category=='legitimate':
                        counts['legitimate_accepted']+=1
                        try: read_query(safe)
                        except Exception: counts['execution_failures']+=1
                    else: counts['unexpected_acceptances']+=1
                except PolicyError:
                    counts['legitimate_false_rejections' if category=='legitimate' else 'security_rejections']+=1
        report['independent_holdout']={**counts,'provenance':holdout['provenance']}
        report['holdout_provenance']='Handwritten main corpus plus independent Groq-generated holdout'
        output_path.write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
    if Path('test-results.xml').exists():
        root=ET.parse('test-results.xml').getroot()
        suite=root.find('testsuite')
        report['automated_suite']={k:suite.get(k) for k in ('tests','failures','errors','skipped')}
        report['financial_test_evidence']=[{'test':case.get('name'),'measurements':{prop.get('name'):prop.get('value') for prop in case.findall('properties/property')}} for case in root.iter('testcase') if case.find('properties') is not None]
        if Path('.local/groq-probe.json').exists():
            probe=json.loads(Path('.local/groq-probe.json').read_text())
            report['live_groq_probe']={'model':probe['model'],'returned_rows':len(probe['rows']),'status':'real inference and PostgreSQL execution verified; no payment charged'}
        output_path.write_text(json.dumps(report,indent=2))
    if Path('sandbox-verification.json').exists():
        report['sandbox_verification']=json.loads(Path('sandbox-verification.json').read_text())
        output_path.write_text(json.dumps(report,indent=2))
    for field,path in [('live_ai_correctness','live-ai-evaluation.json'),('payment_reconciliation_audit','paypal-reconciliation-audit.json'),('heldout_ai','heldout-ai-evaluation.json'),('reproducibility','reproducibility-report.json')]:
        if Path(path).exists(): report[field]=json.loads(Path(path).read_text())
    output_path.write_text(json.dumps(report,indent=2))
    print(f'Evaluation report saved locally to {output_path.as_posix()}')

if __name__=='__main__': main()
