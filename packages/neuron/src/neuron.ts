// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { IObservableDisposable } from '@lumino/disposable';
import { ISignal, Signal } from '@lumino/signaling';

export abstract class Neuron implements IObservableDisposable {
  readonly id: string;

  abstract readonly type: Neuron.Type;

  get disposed(): ISignal<this, void> {
    return this._disposed;
  }

  get fired(): ISignal<this, { id: string; data: Neuron.Matrix }> {
    return this._fired;
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

  abstract input(data: Neuron.Matrix): void;

  protected fire(id: string, data: Neuron.Matrix): void {
    this._fired.emit({ id, data });
  }

  private _disposed = new Signal<this, void>(this);
  private _fired = new Signal<this, { id: string; data: Neuron.Matrix }>(this);
  private _isDisposed = false;
}

export namespace Neuron {
  export type Matrix = (1 | 0)[][];
  export type Type = 'interneuron' | 'motor' | 'sensory';
}
