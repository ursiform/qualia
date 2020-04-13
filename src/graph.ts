// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { UUID } from '@lumino/coreutils';
import { IObservableDisposable } from '@lumino/disposable';
import { ISignal, Signal } from '@lumino/signaling';

export class Graph<T extends IObservableDisposable>
  implements IObservableDisposable {
  get disposed(): ISignal<this, void> {
    return this._disposed;
  }

  get isDisposed(): boolean {
    return this._isDisposed;
  }

  add(node: T, id = UUID.uuid4()) {
    if (this.data.has(id)) {
      return;
    }
    this.data.set(id, node);
    this.graph.set(id, Object.create(null));
  }

  dispose() {
    if (this._isDisposed) {
      return;
    }
    this._isDisposed = true;
    this._disposed.emit(undefined);
  }

  link(a: string, b: string) {
    if (!this.data.has(a)) {
      throw new ReferenceError(`Graph#link: ${a} does not exist.`);
    }
    if (!this.data.has(b)) {
      throw new ReferenceError(`Graph#link: ${b} does not exist.`);
    }
    this.graph.get(a)![b] = null;
  }

  unlink(a: string, b: string) {
    if (!this.data.has(a)) {
      throw new ReferenceError(`Graph#unlink: ${a} does not exist.`);
    }
    if (!this.data.has(b)) {
      throw new ReferenceError(`Graph#unlink: ${b} does not exist.`);
    }
    delete this.graph.get(a)![b];
  }

  protected data = new Map<string, T>();
  protected graph = new Map<string, { [id: string]: null }>();

  private _disposed = new Signal<this, void>(this);
  private _isDisposed = false;
}
