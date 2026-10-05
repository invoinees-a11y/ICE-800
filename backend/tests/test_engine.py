from datetime import date
from ice_engine import CardState, StrategyConfig, analyze_card, analyze_portfolio, simulate_card


def test_unknown_close_triggers_conservative_action():
    c=CardState(account_id='1',name='Card',balance=120,credit_limit=1000)
    x=analyze_card(c,StrategyConfig(),date(2026,10,4))
    assert x['status']=='high'
    assert any(a['title']=='Modo cierre desconocido' for a in x['actions'])


def test_due_date_has_payment_priority():
    c=CardState(account_id='1',name='Card',balance=60,credit_limit=1000,statement_balance=60,next_payment_due_date=date(2026,10,5))
    x=analyze_card(c,StrategyConfig(),date(2026,10,4))
    assert x['actions'][0]['category']=='payment_history'


def test_global_utilization():
    cards=[CardState('1','A',100,1000),CardState('2','B',50,1000)]
    x=analyze_portfolio(cards,StrategyConfig(),date(2026,10,4))
    assert x['global_utilization']==0.075
    assert x['global_action'] is not None


def test_simulation_payment_reduces_utilization():
    c=CardState('1','A',150,1500)
    x=simulate_card(c,StrategyConfig(),payment=75,today=date(2026,10,4))
    assert x['before']['utilization']==0.10
    assert x['after']['utilization']==0.05
