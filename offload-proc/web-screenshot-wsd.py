import sys
import requests
import shutil

arg_url = sys.argv[1]
arg_delay_ms = int(sys.argv[2])
arg_width, arg_height = int(sys.argv[3]), int(sys.argv[4])
arg_fname = sys.argv[5]

# URL = 'http://192.168.1.254:5016/api/screenshot?resX=1280&resY=900&outFormat=png&waitTime=3000&isFullPage=true&url=http://192.168.1.254/hubigraphs/'
URL = 'http://172.17.0.1:5016/api/screenshot?resX=1280&resY=900&outFormat=png&waitTime=3000&isFullPage=true&url=http://192.168.1.254/hubigraphs/'
FNAME = 'test.png'

res = requests.get(URL)
if res.status_code == 200:
    with open(FNAME, 'wb') as f:
        shutil.copyfileobj(res.raw, f)
    print('Image sucessfully Downloaded: ', FNAME)
else:
    print('Image Couldn\'t be retrieved')