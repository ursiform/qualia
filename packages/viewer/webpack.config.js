module.exports = {
  entry: ['./src/index.ts'],
  output: {
    path: __dirname + '/build',
    filename: 'bundle.js'
  },
  bail: true,
  devtool: 'source-map',
  mode: 'development',
  module: {
    rules: [
      { test: /\.css$/, use: ['style-loader', 'css-loader'] },
      { test: /\.tsx?$/, loader: 'ts-loader' }
    ]
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js']
  }
};
