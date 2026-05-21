import { ComponentFixture, TestBed } from '@angular/core/testing';

import { EditChatbotComponent } from './edit-chatbot.component';

describe('EditChatbotComponent', () => {
  let component: EditChatbotComponent;
  let fixture: ComponentFixture<EditChatbotComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EditChatbotComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(EditChatbotComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
