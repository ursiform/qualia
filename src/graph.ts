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

  dispose(): void {
    if (this._isDisposed) {
      return;
    }
    this._isDisposed = true;
    this._disposed.emit(undefined);
  }

  add(node: T, id = UUID.uuid4()) {
    // Add a node.
  }

  link(a: string, b: string) {
    if (!this.data.has(a)) {
      throw new ReferenceError(`Graph#link: ${a} does not exist.`);
    }
    if (!this.data.has(b)) {
      throw new ReferenceError(`Graph#link: ${b} does not exist.`);
    }
    // Create a link.
  }

  unlink(a: T, b: T): void {
    // Remove an edge.
  }

  protected data =  new Map<string, string[]>();

  private _disposed = new Signal<this, void>(this);
  private _isDisposed = false;
}
