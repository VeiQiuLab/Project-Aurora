"""Small strict command/snapshot boundary; never accepts network credentials."""
import re

REQUEST_KEYS = {'action', 'private_ids', 'group_ids', 'self_id', 'trigger', 'message_key', 'revision', 'text', 'confirmation'}
REQUEST_KEYS |= {'group_id','consent','sender_id','after','before','query','offset','key','scope','target'}
SNAPSHOT_KEYS = {'status', 'error', 'configured', 'self_id', 'private_ids', 'group_ids', 'trigger', 'messages',
                 'automatic', 'auto_group_ids', 'auto_status', 'queued'}
MESSAGE_KEYS = {'key', 'source', 'conversation_id', 'sender_id', 'message_id', 'timestamp', 'text',
                'supported', 'state', 'reply', 'revision', 'confirmation', 'sent_message_id'}
STATUSES = {'disabled', 'connecting', 'connected', 'reconnecting', 'error'}
STATES = {'received', 'queued', 'generating', 'preview', 'cancelled', 'sending', 'sent', 'failed', 'unknown'}
ERRORS = {'', 'QQ_NOT_CONFIGURED', 'QQ_UNAVAILABLE', 'QQ_AUTH_FAILED', 'QQ_IDENTITY_INVALID', 'QQ_REJECTED',
          'QQ_SEND_UNKNOWN', 'QQ_INVALID_REQUEST', 'QQ_NOT_CONNECTED', 'QQ_NOT_FOUND', 'QQ_CONFLICT',
          'QQ_NOT_AUTHORIZED', 'QQ_BUSY', 'QQ_GENERATION_FAILED', 'QQ_PERSISTENCE_FAILED', 'QQ_ALREADY_SENT'}


def identity(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[1-9][0-9]{0,18}', value)) and int(value) < 2**63


def ids(value):
    return isinstance(value, list) and len(value) <= 20 and all(identity(v) for v in value) and len(set(value)) == len(value)


def fingerprint(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[a-f0-9]{64}', value))


def validate_request(p):
    if not isinstance(p, dict):
        raise ValueError()
    action = p.get('action')
    if isinstance(action,str) and action.startswith('archive_'):
        return validate_archive_request(p)
    fields = {'snapshot': set(), 'disconnect': set(), 'disable_auto': set(), 'disable_natural': set(),
              'enable_natural': {'self_id', 'group_ids'},
              'enable_auto': {'self_id', 'group_ids'}, 'connect': {'private_ids', 'group_ids', 'trigger'},
              'generate': {'message_key'}, 'cancel': {'message_key'},
              'edit': {'message_key', 'revision', 'text'}, 'prepare': {'message_key', 'revision'},
              'send': {'message_key', 'revision', 'confirmation'}}
    if action not in fields or set(p) != fields[action] | {'action'}:
        raise ValueError()
    if action in ('enable_auto','enable_natural') and (not identity(p['self_id']) or not ids(p['group_ids']) or not p['group_ids']):
        raise ValueError()
    if action == 'connect' and (not ids(p['private_ids']) or not ids(p['group_ids'])
            or not (p['private_ids'] or p['group_ids']) or not isinstance(p['trigger'], str)
            or len(p['trigger']) > 40 or any(ord(c) < 32 for c in p['trigger'])):
        raise ValueError()
    if 'message_key' in p and not fingerprint(p['message_key']):
        raise ValueError()
    if 'revision' in p and (type(p['revision']) is not int or not 0 < p['revision'] < 2**31):
        raise ValueError()
    if 'text' in p and (not isinstance(p['text'], str) or not p['text'].strip() or len(p['text']) > 4096):
        raise ValueError()
    if 'text' in p:
        p['text'].encode('utf-8')
    if 'confirmation' in p and not fingerprint(p['confirmation']):
        raise ValueError()


def validate_snapshot(p):
    if not isinstance(p, dict) or set(p)-{'archive','natural'} != SNAPSHOT_KEYS or p['status'] not in STATUSES or p['error'] not in ERRORS:
        raise ValueError()
    if 'natural' in p and (type(p['natural']) is not bool or (p['natural'] and not p['automatic'])):raise ValueError()
    if 'archive' in p: validate_archive_snapshot(p['archive'])
    if type(p['configured']) is not bool or not isinstance(p['self_id'], str) or (p['self_id'] and not identity(p['self_id'])):
        raise ValueError()
    if (type(p['automatic']) is not bool or not ids(p['auto_group_ids'])
            or not set(p['auto_group_ids']) <= set(p['group_ids'])
            or p['auto_status'] not in {'off', 'ready', 'busy', 'paused', 'reconnecting'}
            or type(p['queued']) is not int or not 0 <= p['queued'] <= 6):
        raise ValueError()
    if not ids(p['private_ids']) or not ids(p['group_ids']) or not isinstance(p['trigger'], str) or len(p['trigger']) > 40:
        raise ValueError()
    if not isinstance(p['messages'], list) or len(p['messages']) > 8:
        raise ValueError()
    for m in p['messages']:
        if (not isinstance(m, dict) or set(m) != MESSAGE_KEYS or not fingerprint(m['key'])
                or m['source'] not in {'private', 'group'} or m['state'] not in STATES
                or not identity(m['sender_id']) or not isinstance(m['conversation_id'], str)
                or not re.fullmatch(r'qq:[1-9][0-9]*:(private|group):[1-9][0-9]*:[1-9][0-9]*', m['conversation_id'])
                or not isinstance(m['message_id'], str) or not re.fullmatch(r'-?[0-9]{1,20}', m['message_id'])
                or type(m['timestamp']) is not int or m['timestamp'] < 1 or type(m['supported']) is not bool
                or type(m['revision']) is not int or not 0 <= m['revision'] < 2**31
                or not isinstance(m['text'], str) or len(m['text']) > 2048
                or not isinstance(m['reply'], str) or len(m['reply']) > 4096
                or not isinstance(m['sent_message_id'], str) or len(m['sent_message_id']) > 20
                or not re.fullmatch(r'(-?[0-9]+)?', m['sent_message_id'])
                or (m['confirmation'] != '' and not fingerprint(m['confirmation']))):
            raise ValueError()


def validate_archive_request(p):
    common={'action','self_id','group_id'}
    fields={'archive_enable':{'consent'},'archive_disable':set(),'archive_export':set(),
        'archive_query':{'sender_id','after','before','query','offset'},'archive_around':{'key'},
        'archive_prepare_delete':{'scope','target'},'archive_delete':{'scope','target','confirmation'}}
    action=p.get('action')
    if action not in fields or set(p)!=common|fields[action] or not identity(p['self_id']) or not identity(p['group_id']):raise ValueError()
    if action=='archive_enable' and p['consent'] is not True:raise ValueError()
    if action=='archive_query':
        if (p['sender_id'] and not identity(p['sender_id'])) or not isinstance(p['sender_id'],str):raise ValueError()
        if any(type(p[k]) is not int or not 0<=p[k]<=2**53-1 for k in ('after','before','offset')) or p['after']>p['before']:raise ValueError()
        if p['offset']>1000000 or not isinstance(p['query'],str) or len(p['query'])>128:raise ValueError()
        p['query'].encode('utf-8')
    if action=='archive_around' and not fingerprint(p['key']):raise ValueError()
    if action in ('archive_prepare_delete','archive_delete'):
        if p['scope'] not in ('message','sender','group'):raise ValueError()
        if not ((p['scope']=='group' and p['target']=='') or (p['scope']=='sender' and identity(p['target']))
            or (p['scope']=='message' and fingerprint(p['target']))):raise ValueError()
    if action=='archive_delete' and not fingerprint(p['confirmation']):raise ValueError()


def validate_archive_snapshot(a):
    if not isinstance(a,dict) or set(a)!={'policies','error','rows','account_id','group_id','export_file','confirmation'}:raise ValueError()
    if a['error'] not in ('','QQ_ARCHIVE_FAILED','QQ_NOT_AUTHORIZED','QQ_NOT_FOUND','QQ_CONFLICT'):raise ValueError()
    if not isinstance(a['export_file'],str) or len(a['export_file'])>1024:raise ValueError()
    if any(not isinstance(a[k],str) or (a[k] and not identity(a[k])) for k in ('account_id','group_id')):raise ValueError()
    if a['confirmation'] and not fingerprint(a['confirmation']):raise ValueError()
    if not isinstance(a['policies'],list) or len(a['policies'])>400:raise ValueError()
    for p in a['policies']:
        if set(p)!={'account_id','group_id','enabled'} or not identity(p['account_id']) or not identity(p['group_id']) or p['enabled'] not in (0,1):raise ValueError()
    if not isinstance(a['rows'],list) or len(a['rows'])>20:raise ValueError()
    fields={'key','platform','account_id','group_id','sender_id','display_name','message_id','timestamp','message_type','text','ingested_at','truncated'}
    for r in a['rows']:
        if set(r)!=fields or not fingerprint(r['key']) or r['platform']!='qq' or r['account_id']!=a['account_id'] or r['group_id']!=a['group_id']:raise ValueError()
        if not identity(r['sender_id']) or not isinstance(r['display_name'],str) or len(r['display_name'])>256:raise ValueError()
        if r['message_type'] not in ('text','mixed','raw_text') or not isinstance(r['text'],str) or len(r['text'])>2048 or type(r['truncated']) is not bool:raise ValueError()
        if not isinstance(r['message_id'],str) or not re.fullmatch(r'-?[0-9]{1,20}',r['message_id']):raise ValueError()
        if any(type(r[k]) is not int or not 1<=r[k]<=2**53-1 for k in ('timestamp','ingested_at')):raise ValueError()
