// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { IObservableDisposable } from '@lumino/disposable';
import { ISignal, Signal } from '@lumino/signaling';

export abstract class Neuron implements IObservableDisposable {
  abstract readonly type: Neuron.Type;

  get disposed(): ISignal<this, void> {
    return this._disposed;
  }

  get isDisposed(): boolean {
    return this._isDisposed;
  }

  dispose(): void {
    if (this._isDisposed) {
      return;
    }
    this._isDisposed = true;
    this._disposed.emit(undefined);
    Signal.clearData(this);
  }

  abstract async fire(input: Neuron.Matrix): Promise<Neuron.Matrix>;

  private _disposed = new Signal<this, void>(this);
  private _isDisposed = false;
}

export namespace Neuron {
  export type Matrix = (1 | 0)[][];
  export type Type = 'interneuron' | 'motor' | 'sensory';
}
