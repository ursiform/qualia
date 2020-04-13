// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { IDisposable } from '@lumino/disposable';
import { Graph } from './graph';
import { Neuron } from './neuron';

export class Connectome implements IDisposable {
  graph = new Graph<Neuron>();

  get isDisposed(): boolean {
    return this.graph.isDisposed;
  }

  dispose() {
    this.graph.dispose();
  }
}
