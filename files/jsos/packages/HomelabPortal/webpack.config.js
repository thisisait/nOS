const path = require('path');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const mode = process.env.NODE_ENV || 'development';

module.exports = {
  mode,
  devtool: mode === 'production' ? false : 'source-map',
  entry: [
    path.resolve(__dirname, 'index.js'),
    path.resolve(__dirname, 'index.scss'),
  ],
  externals: {
    osjs: 'OSjs',
  },
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'main.js',
    sourceMapFilename: 'main.js.map',
    library: 'OSjsHomelabPortal',
    libraryTarget: 'umd',
  },
  module: {
    rules: [
      {
        test: /\.js$/,
        exclude: /node_modules/,
        use: {
          loader: 'babel-loader',
        },
      },
      {
        test: /\.scss$/,
        use: [
          MiniCssExtractPlugin.loader,
          'css-loader',
          'sass-loader',
        ],
      },
    ],
  },
  plugins: [
    new MiniCssExtractPlugin({ filename: 'main.css' }),
  ],
};
