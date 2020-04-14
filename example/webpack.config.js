module.exports = {
  entry: ['./lib/index.js'],
  output: {
    path: __dirname + '/build',
    filename: 'bundle.js'
  },
  bail: true,
  devtool: 'source-map',
  mode: 'development',
  module: {
    rules: [
      { test: /\.css$/, use: ['style-loader', 'css-loader'] }
    ]
  }
};