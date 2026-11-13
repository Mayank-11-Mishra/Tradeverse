"""Opt-in broker-session vault for the local Windows owner.
Windows: DPAPI CurrentUser (machine/user-bound encrypted bytes).
Other OS: Fernet only when TRADING_VAULT_KEY is supplied; otherwise no persistence.
Tokens must still be verified online before unlocking the terminal.
"""
from __future__ import annotations
import json,os,sys
from pathlib import Path
from typing import Any
from app.database.store import DATA

FILE=DATA/'broker_sessions.vault'

def _windows_protect(data:bytes,unprotect:bool=False)->bytes:
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_byte))]
    inp_buffer=ctypes.create_string_buffer(data)
    inp=Blob(len(data),ctypes.cast(inp_buffer,ctypes.POINTER(ctypes.c_byte)))
    output=Blob()
    crypt=ctypes.windll.crypt32
    flags=0x01 # CRYPTPROTECT_UI_FORBIDDEN
    fn=crypt.CryptUnprotectData if unprotect else crypt.CryptProtectData
    ok=(fn(ctypes.byref(inp),None,None,None,None,flags,ctypes.byref(output)) if unprotect
        else fn(ctypes.byref(inp),None,None,None,None,flags,ctypes.byref(output)))
    if not ok:raise OSError('Windows DPAPI could not decrypt/encrypt session data')
    try:return ctypes.string_at(output.pbData,output.cbData)
    finally:
        free=ctypes.windll.kernel32.LocalFree
        free.argtypes=[ctypes.c_void_p]
        free.restype=ctypes.c_void_p
        free(output.pbData)

def _encrypt(data:bytes)->bytes:
    if sys.platform=='win32':return _windows_protect(data)
    key=os.getenv('TRADING_VAULT_KEY')
    if not key:raise RuntimeError('Persistence requires TRADING_VAULT_KEY on non-Windows systems')
    from cryptography.fernet import Fernet
    return Fernet(key.encode()).encrypt(data)

def _decrypt(data:bytes)->bytes:
    if sys.platform=='win32':return _windows_protect(data,True)
    key=os.getenv('TRADING_VAULT_KEY')
    if not key:raise RuntimeError('TRADING_VAULT_KEY is missing')
    from cryptography.fernet import Fernet
    return Fernet(key.encode()).decrypt(data)

def enabled():return os.getenv('SAVE_BROKER_TOKENS','yes' if sys.platform=='win32' else 'no').lower()=='yes'

def read_all()->dict[str,Any]:
    if not enabled() or not FILE.exists():return {}
    try:
        data=json.loads(_decrypt(FILE.read_bytes()))
        return data if isinstance(data,dict) else {}
    except Exception:
        # No exceptions with raw secret bytes ever reach HTTP responses or logs.
        return {}

def write_all(items:dict[str,Any]):
    if not enabled():return
    data=_encrypt(json.dumps(items,separators=(',',':')).encode())
    tmp=FILE.with_suffix('.vault.tmp')
    tmp.write_bytes(data)
    if sys.platform!='win32':os.chmod(tmp,0o600)
    os.replace(tmp,FILE)

def save_session(account:str,broker:str,account_id:str,credentials:dict):
    if not enabled():return
    items=read_all()
    items[account]={'broker':broker,'account_id':account_id,'credentials':credentials}
    write_all(items)

def forget_session(account:str):
    if not enabled():return
    items=read_all()
    if account in items:
        del items[account]
        write_all(items)
