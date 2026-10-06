# Third-party components

The WDA runtime fetches Appium WebDriverAgent 16.14.0 at commit
`d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6` from
https://github.com/appium/WebDriverAgent. WDA is BSD licensed; its original
LICENSE stays in the external checkout. WDA source, builds and signing data
are not bundled into this plugin.

USB forwarding uses appium-ios-device 3.1.24 under Apache-2.0, installed via
tooling/package-lock.json. The dependency's license remains in node_modules.
The Python MCP server uses only the Python standard library.
