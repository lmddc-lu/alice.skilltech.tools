import { ComponentFixture, TestBed } from '@angular/core/testing';

import { NewChatbotComponent } from './new-chatbot.component';

describe('NewChatbotComponent', () => {
  let component: NewChatbotComponent;
  let fixture: ComponentFixture<NewChatbotComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NewChatbotComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(NewChatbotComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
