
![GitHub tag (latest by date)](https://img.shields.io/github/v/tag/fohrloop/dash-uploader)&nbsp;![PyPI](https://img.shields.io/pypi/v/dash-uploader)&nbsp;![PyPI - Downloads](https://img.shields.io/pypi/dm/dash-uploader)&nbsp;![GitHub](https://img.shields.io/github/license/fohrloop/dash-uploader)

![upload large files with dash-uploader](https://github.com/fohrloop/dash-uploader/blob/0.2.0/docs/upload-demo.gif?raw=true)

# 📤 dash-uploader-ng
The upload package for [Dash](https://dash.plotly.com/) applications using large data files. A maintained, security-patched fork of [dash-uploader](https://github.com/fohrloop/dash-uploader).

### 🏠 Homepage & Documentation
[https://github.com/obliviance/dash-uploader-ng](https://github.com/obliviance/dash-uploader-ng)


## Short summary
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 💾 Data file size has no limits. (Except the hard disk size)<bR>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ☎ Call easily a callback after uploading is finished.<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 📦 Upload files using [flow.js](https://github.com/flowjs/flow.js/) 
<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ✅ Works with Dash 2.0+ (verified on Dash 4.x) & Python 3.10+.<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 🔒 Security-patched fork of dash-uploader (fixes CVE-2026-38360).<br>



## Installing
```
pip install dash-uploader-ng
```

## Usage


### Simple example

```python
import dash
import dash_html_components as html
import dash_uploader_ng as du

app = dash.Dash(__name__)

# 1) configure the upload folder
du.configure_upload(app, r"C:\tmp\Uploads")

# 2) Use the Upload component
app.layout = html.Div([
    du.Upload(),
])

if __name__ == '__main__':
    app.run_server(debug=True)

```

