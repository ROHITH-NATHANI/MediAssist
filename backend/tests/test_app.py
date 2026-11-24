import os,tempfile
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mkdtemp()+'/test.db'
os.environ['AGENT_MODE']='offline'
os.environ['DEMO_SEED']='true'
import fitz,pytest
from fastapi.testclient import TestClient
from app.main import app
from app.agents import route
@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:yield c

def login(c,who='patient'):
    r=c.post('/api/auth/login',json={'email':who+'@demo.test','password':'DemoPass123!'});assert r.status_code==200,r.text;return {'Authorization':'Bearer '+r.json()['token']}
def test_auth(client):
    assert client.get('/api/me').status_code==401
    h=login(client);assert client.get('/api/me',headers=h).json()['role']=='patient'
    assert client.get('/api/admin/stats',headers=h).status_code==403
    assert client.post('/api/auth/login',json={'email':'patient@demo.test','password':'wrong'}).status_code==401

def test_booking(client):
    p=login(client);d=login(client,'doctor1');slot=client.get('/api/slots',headers=p).json()[0]
    assert client.post('/api/appointments',headers=d,json={'slot_id':slot['id']}).status_code==403
    r=client.post('/api/appointments',headers=p,json={'slot_id':slot['id']});assert r.status_code==201
    assert client.post('/api/appointments',headers=p,json={'slot_id':slot['id']}).status_code==409
    assert client.patch('/api/appointments/'+str(r.json()['id'])+'/cancel',headers=p).status_code==200
    assert client.post('/api/appointments',headers=p,json={'slot_id':slot['id']}).status_code==201

def test_report_and_isolation(client):
    h=login(client);doc=fitz.open();p=doc.new_page();p.insert_text((40,40),'SYNTHETIC CBC report: hemoglobin example');pdf=doc.tobytes();doc.close()
    assert client.post('/api/reports',headers=h,files={'file':('bad.pdf',b'bad','application/pdf')}).status_code==415
    r=client.post('/api/reports',headers=h,files={'file':('demo.pdf',pdf,'application/pdf')});assert r.status_code==201;r_id=r.json()['id']
    assert client.get(f'/api/reports/{r_id}/download',headers=h).content==pdf
    other=client.post('/api/auth/register',json={'email':'other@demo.test','password':'OtherPass123!','name':'Other Demo'}).json();oh={'Authorization':'Bearer '+other['token']}
    assert client.get(f'/api/reports/{r_id}/download',headers=oh).status_code==404
    assert client.post('/api/chat',headers=oh,json={'message':'explain report','report_id':r_id}).status_code==404
    res=client.post('/api/chat',headers=h,json={'message':'Explain blood test report and book doctor appointment and show medication reminders','report_id':r_id}).json()
    assert {x['agent'] for x in res['trace']}=={'supervisor','health','report','appointment','medication','safety'}
    assert 'SYNTHETIC CBC' in res['answer'] and res['slots'] and res['sources']

def test_medications(client):
    h=login(client);r=client.post('/api/medications',headers=h,json={'name':'Demo medication A','instructions':'Synthetic prescribed schedule','time':'08:00','timezone':'Asia/Kolkata'});assert r.status_code==201
    i=r.json()['id'];assert client.post(f'/api/medications/{i}/taken',headers=h).json()['taken'];assert client.post(f'/api/medications/{i}/taken',headers=h).status_code==200
    assert client.delete(f'/api/medications/{i}',headers=h).status_code==200

def test_urgent(client):
    h=login(client);r=client.post('/api/chat',headers=h,json={'message':'I have chest pain book an appointment'}).json();assert r['urgent'] and not r['slots']

def test_admin(client):
    h=login(client,'admin');assert client.get('/api/admin/stats',headers=h).status_code==200
    assert client.get('/api/reports',headers=h).status_code==403
    assert client.post('/api/chat',headers=h,json={'message':'test'}).status_code==403
@pytest.mark.parametrize('query,expected',[('Show appointments','appointment'),('Explain CBC','report'),('medication reminders','medication'),('what is blood pressure','health')])
def test_routing(query,expected):assert expected in route(query)
