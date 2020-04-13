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
    if (this.nodes.has(id)) {
      return;
    }
    this.nodes.set(id, { node, edges: new Map() });
  }

  dispose() {
    if (this._isDisposed) {
      return;
    }
    this._isDisposed = true;
    this._disposed.emit(undefined);
  }

  link(a: string, b: string) {
    if (!this.nodes.has(a)) {
      throw new ReferenceError(`Graph#link: ${a} does not exist.`);
    }
    if (!this.nodes.has(b)) {
      throw new ReferenceError(`Graph#link: ${b} does not exist.`);
    }
    this.nodes.get(a)!.edges.set(b);
  }

  unlink(a: string, b: string) {
    if (!this.nodes.has(a)) {
      throw new ReferenceError(`Graph#unlink: ${a} does not exist.`);
    }
    if (!this.nodes.has(b)) {
      throw new ReferenceError(`Graph#unlink: ${b} does not exist.`);
    }
    this.nodes.get(a)!.edges.delete(b);
  }

  protected nodes = new Map<string, { node: T; edges: Map<string, void> }>();

  private _disposed = new Signal<this, void>(this);
  private _isDisposed = false;
}
