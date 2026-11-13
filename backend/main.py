from app.api.server import app

if __name__=='__main__':
    import uvicorn
    uvicorn.run('app.api.server:app',host='127.0.0.1',port=8000,reload=False)
