"""Owned, authenticated loopback OneBot 11 transport for the desktop.

The legacy automatic-reply connector is deliberately not instantiated here.
HTTP action names and event adaptation retain the existing OneBot boundary.
"""
import asyncio
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from .onebot_client import OneBotClient


class TransportError(RuntimeError):
    def __init__(self, code, *, definite=False):
        super().__init__(code)
        self.code, self.definite = code, definite


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class NoWSRedirect(connect):
    def process_redirect(self, exc):
        return exc


def local_endpoint(value, scheme):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != scheme or parsed.hostname not in {'127.0.0.1', '::1'}
            or not parsed.port or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/', '/event')):
        raise ValueError('Invalid local QQ configuration')
    if scheme == 'http' and parsed.path not in ('', '/'):
        raise ValueError('Invalid local QQ configuration')
    return value.rstrip('/')


class ControlledTransport(OneBotClient):
    def __init__(self, http_endpoint, token, ws_endpoint):
        http_endpoint = local_endpoint(http_endpoint, 'http') if http_endpoint else ''
        ws_endpoint = local_endpoint(ws_endpoint, 'ws')
        if not token or len(token) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in token):
            raise ValueError('QQ authentication must be configured')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        super().__init__(http_endpoint, token, ws_endpoint=ws_endpoint, opener=opener.open, timeout=3)
        self.http_endpoint = http_endpoint  # no legacy implicit HTTP fallback in WS-only mode
        self.socket = None
        self.reader = None
        self.pending = {}
        self.incoming = asyncio.Queue(maxsize=128)
        self.self_name = ''

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get('AURORA_QQ_HTTP_URL', ''), os.environ.get('AURORA_QQ_TOKEN', ''),
                   os.environ.get('AURORA_QQ_WS_URL', ''))

    def _action(self, action, params=None):
        # Strict success/rejection classification. A transport failure during a
        # send is ambiguous: OneBot has no idempotency key, so it cannot be retried.
        request = urllib.request.Request(self.http_endpoint + '/' + action,
            data=json.dumps(params or {}).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.access_token})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError()
            result = json.loads(raw)
            if not isinstance(result, dict) or type(result.get('retcode')) is not int:
                raise ValueError()
            if result.get('status') == 'failed' and result['retcode'] not in (0, 1):
                raise TransportError('QQ_REJECTED', definite=True)
            if result.get('status') != 'ok' or result['retcode'] != 0 or not isinstance(result.get('data'), dict):
                raise ValueError()
            return result['data']
        except TransportError:
            raise
        except urllib.error.HTTPError as exc:
            raise TransportError('QQ_AUTH_FAILED' if exc.code in (401, 403) else 'QQ_UNAVAILABLE',
                                 definite=exc.code in (401, 403)) from None
        except Exception:
            raise TransportError('QQ_UNAVAILABLE') from None

    async def open(self):
        identity = await asyncio.to_thread(self._action, 'get_login_info') if self.http_endpoint else None
        try:
            self.socket = await NoWSRedirect(self.ws_endpoint, additional_headers={'Authorization': 'Bearer ' + self.access_token},
                proxy=None, open_timeout=3, close_timeout=1, max_size=65536)
        except InvalidStatus as error:
            raise TransportError('QQ_AUTH_FAILED' if error.response.status_code in (401, 403) else 'QQ_UNAVAILABLE') from None
        except Exception:
            raise TransportError('QQ_UNAVAILABLE') from None
        self.reader = asyncio.create_task(self._read())
        if identity is None:
            identity = await self._ws_action('get_login_info', {})
        user_id = identity.get('user_id')
        if type(user_id) is not int or not 0 < user_id < 2**63:
            raise TransportError('QQ_IDENTITY_INVALID')
        nickname = identity.get('nickname')
        self.self_name = nickname if (isinstance(nickname, str) and 0 < len(nickname) <= 64
            and nickname == nickname.strip() and not any(ord(c) < 32 for c in nickname)) else ''
        return str(user_id)

    async def _read(self):
        try:
            async for raw in self.socket:
                if not isinstance(raw, str):
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if (isinstance(event, dict) and not event.get('post_type')
                        and event.get('status') == 'failed' and event.get('retcode') == 1403):
                    for future in self.pending.values():
                        if not future.done():
                            future.set_exception(TransportError('QQ_AUTH_FAILED', definite=True))
                    break  # NapCat also supports post-handshake token rejection
                if isinstance(event, dict) and 'echo' in event:
                    echo = event['echo']
                    future = self.pending.get(echo) if isinstance(echo, str) else None
                    if future and not future.done():
                        future.set_result(event)
                else:
                    # Bounded backpressure, not silent loss when archiving a busy
                    # authorized group. WebSocket/TCP buffers remain bounded too.
                    await self.incoming.put(event)
        except Exception:
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(TransportError('QQ_UNAVAILABLE'))

    async def _ws_action(self, action, params):
        echo = 'aurora-' + secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await self.socket.send(json.dumps({'action': action, 'params': params, 'echo': echo}))
            result = await asyncio.wait_for(future, self.timeout)
            if isinstance(result, dict) and type(result.get('retcode')) is int:
                if result.get('status') == 'failed' and result['retcode'] not in (0, 1):
                    raise TransportError('QQ_REJECTED', definite=True)
                if result.get('status') == 'ok' and result['retcode'] == 0 and isinstance(result.get('data'), dict):
                    return result['data']
            raise TransportError('QQ_UNAVAILABLE')
        except TransportError:
            raise
        except Exception:
            raise TransportError('QQ_UNAVAILABLE') from None
        finally:
            self.pending.pop(echo, None)

    async def events(self):
        while self.reader and (not self.reader.done() or not self.incoming.empty()):
            if not self.incoming.empty():
                yield self.incoming.get_nowait()
                continue
            get = asyncio.create_task(self.incoming.get())
            try:
                done, _ = await asyncio.wait([get, self.reader], return_when=asyncio.FIRST_COMPLETED)
                if get in done:
                    yield get.result()
                else:
                    break
            finally:
                if not get.done():
                    get.cancel()
                await asyncio.gather(get, return_exceptions=True)

    async def send_text(self, message, text):
        action = 'send_group_msg' if message.is_group else 'send_private_msg'
        target = {'group_id': int(message.group_id)} if message.is_group else {'user_id': int(message.sender_id)}
        # Explicit text segments: generated CQ strings remain literal text.
        params = {**target, 'message': [{'type': 'text', 'data': {'text': text}}]}
        data = (await asyncio.to_thread(self._action, action, params) if self.http_endpoint
                else await self._ws_action(action, params))
        message_id = data.get('message_id')
        if type(message_id) is not int or not -(2**63) < message_id < 2**63:
            raise TransportError('QQ_SEND_UNKNOWN')
        return str(message_id)

    async def close(self):
        if self.socket:
            await self.socket.close()
            self.socket = None
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
            self.reader = None
