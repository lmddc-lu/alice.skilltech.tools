import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChatAccessDialogComponent } from './chat-access-dialog.component';

describe('ChatAccessDialogComponent', () => {
  let component: ChatAccessDialogComponent;
  let fixture: ComponentFixture<ChatAccessDialogComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChatAccessDialogComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ChatAccessDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
